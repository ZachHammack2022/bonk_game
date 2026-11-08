"""What the server is doing, for whoever runs it: structured logs and the
numbers behind /metrics.

Logs are one JSON object per line on stderr, e.g.
    {"t": "2026-11-03T18:00:00Z", "event": "match_started", "room": "ABCD", ...}
so a host's log viewer can search and filter them.

History keeps a copy of those numbers every minute in SQLite (BONK_METRICS_DB),
so the /admin page can chart them over days, across restarts and deploys.
"""
import collections
import datetime
import hashlib
import json
import logging
import math
import secrets
import sqlite3
import time

log = logging.getLogger("bonk")


def event(name, level=logging.INFO, /, **fields):
    """Log one thing that happened (room_created, match_ended, error...)."""
    if not log.isEnabledFor(level):
        return
    t = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log.log(level, json.dumps({"t": t, "event": name, **fields}, separators=(",", ":"), default=str))


def setup_logging():
    """Plain JSON lines on stderr (python -m bonk_game.server does this)."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


class Stats:
    """Counters for the whole server. Tick times are kept for the last
    TICK_SAMPLES ticks (across every room), enough for a steady p99."""

    TICK_SAMPLES = 3000

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.ticks = collections.deque(maxlen=self.TICK_SAMPLES)  # seconds per tick
        self.ticks_total = 0
        self.late_ticks = 0            # a room fell behind 30 ticks a second
        self.bytes_sent = 0            # JSON text sent over WebSockets
        self.wire_bytes = 0            # what that came to on the wire (compressed frames)
        self.messages_sent = 0
        self.matches_started = 0
        self.matches_finished = 0
        self.rooms_created = 0
        self.connections = 0           # open WebSockets
        self.refused_old_clients = 0   # tabs told to refresh

    def count_wire(self, transport):
        """Count what a WebSocket's frames take on the wire (after
        permessage-deflate). aiohttp writes every frame with transport.write."""
        write = getattr(transport, "write", None)
        if write is None:
            return

        def counted(data):
            self.wire_bytes += len(data)
            write(data)
        transport.write = counted

    def tick(self, seconds):
        self.ticks.append(seconds)
        self.ticks_total += 1

    def sent(self, nbytes):
        self.bytes_sent += nbytes
        self.messages_sent += 1

    def tick_ms(self):
        """(average, p99) of recent tick times in ms, or (0, 0)."""
        if not self.ticks:
            return 0.0, 0.0
        s = sorted(self.ticks)
        avg = sum(s) / len(s)
        p99 = s[min(len(s) - 1, int(len(s) * 0.99))]
        return avg * 1000, p99 * 1000

    def snapshot(self, rooms):
        """Everything /metrics reports. rooms: the RoomManager."""
        avg, p99 = self.tick_ms()
        all_rooms = list(rooms.rooms.values())
        regions = ping_by_region(all_rooms)
        online = [m for r in all_rooms for m in r.members.values() if m.connected]
        everyone = sorted(m.rtt for m in online if m.rtt is not None)
        delays = sorted(m.delay for m in online if m.delay is not None)
        play_min = sum(g["play_min"] for g in regions.values())
        return {
            "uptime_seconds": round(self.clock() - self.started, 1),
            "draining": rooms.draining,
            "rooms": len(all_rooms),
            "members": sum(len(r.members) for r in all_rooms),
            "members_connected": sum(len(r.connected) for r in all_rooms),
            "matches_running": sum(1 for r in all_rooms if r.match is not None),
            "rooms_locked": sum(1 for r in all_rooms if r.settings.get("password")),
            "connections": self.connections,
            "tick_ms_avg": round(avg, 3),
            "tick_ms_p99": round(p99, 3),
            "ticks_total": self.ticks_total,
            "late_ticks_total": self.late_ticks,
            "bytes_sent_total": self.bytes_sent,
            "wire_bytes_sent_total": self.wire_bytes,
            "messages_sent_total": self.messages_sent,
            "rooms_created_total": self.rooms_created,
            "matches_started_total": self.matches_started,
            "matches_finished_total": self.matches_finished,
            "refused_old_clients_total": self.refused_old_clients,
            # Everyone's round trip (what their browsers last said), and by region
            "ping_med_ms": _pct(everyone, 0.5),
            "ping_p95_ms": _pct(everyone, 0.95),
            # How far behind the newest states matches are drawn, and how
            # often states stall (over the last minute, per minute of play)
            "delay_med_ms": _pct(delays, 0.5),
            "stalls_per_min": round(sum(g["stalls"] for g in regions.values()) / play_min, 2) if play_min else None,
            "regions": regions,
        }


def _pct(sorted_values, q):
    """A percentile of already-sorted numbers, or None if there are none."""
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * q))]


SLOW_MS = 150  # a round trip people start to feel
STATES_PER_MIN = 30 * 60
PLAYING_STATES = 10 * 30  # in the last minute: someone in a match (10 s of states)
STALLING_PER_MIN = 1      # stalls a minute: someone the network's letting down


def ping_by_region(rooms, now=None):
    """Who's online where, and how laggy: {region: {
        "players", "known" (how many said their ping), "med", "p95", "slow"
        (round trips: typical, the worst 5%, how many over SLOW_MS);
        "delay_known", "delay_med", "delay_p95": how far behind the newest
        states their matches are drawn (the playback clock's delay), ms;
        "play_min": minutes of states their browsers got in the last minute,
        "stalls": how many came after a stall (over 100 ms since the last);
        "playing": players in a match most of that minute, "stalling": how
        many of them stalled more than STALLING_PER_MIN a minute}}.
    A region is where the connection came in (Fly's region code,
    limits.client_region)."""
    now = time.monotonic() if now is None else now
    groups = {}
    for room in rooms:
        for m in room.members.values():
            if not m.connected:
                continue
            g = groups.setdefault(m.region or "direct", {"n": 0, "rtts": [], "delays": [], "states": 0, "stalls": 0,
                                                          "playing": 0, "stalling": 0})
            g["n"] += 1
            if m.rtt is not None:
                g["rtts"].append(m.rtt)
            if m.delay is not None:
                g["delays"].append(m.delay)
            states, stalls = m.stall_window(now)
            g["states"] += states
            g["stalls"] += stalls
            if states >= PLAYING_STATES:
                g["playing"] += 1
                # (more than once a minute, and more than once: one stall in
                # the 40 s someone's been playing isn't "often")
                if stalls > 1 and stalls / (states / STATES_PER_MIN) > STALLING_PER_MIN:
                    g["stalling"] += 1
    out = {}
    for region, g in groups.items():
        rtts, delays = sorted(g["rtts"]), sorted(g["delays"])
        out[region] = {"players": g["n"], "known": len(rtts), "med": _pct(rtts, 0.5), "p95": _pct(rtts, 0.95),
                       "slow": sum(1 for t in rtts if t > SLOW_MS),
                       "delay_known": len(delays), "delay_med": _pct(delays, 0.5), "delay_p95": _pct(delays, 0.95),
                       "play_min": round(g["states"] / STATES_PER_MIN, 3), "stalls": g["stalls"],
                       "playing": g["playing"], "stalling": g["stalling"]}
    return out


def prometheus(snap):
    """The same numbers in Prometheus' text format (counters end in _total)."""
    lines = []
    for k, v in snap.items():
        if not isinstance(v, (int, float)):  # (the by-region table, a ping nobody's sent yet)
            continue
        name = "bonk_" + k
        kind = "counter" if k.endswith("_total") else "gauge"
        lines.append(f"# TYPE {name} {kind}")
        lines.append(f"{name} {int(v) if isinstance(v, bool) else v}")
    return "\n".join(lines) + "\n"


STATS = Stats()


class History:
    """The server's numbers (Stats.snapshot and friends) every SAMPLE_EVERY
    seconds, kept for KEEP_DAYS. Counters (names ending in _total) start
    again from 0 when the server restarts; series() turns them into how
    much happened in each stretch of time, allowing for that."""

    SAMPLE_EVERY = 60    # seconds
    KEEP_DAYS = 90
    SCHEMA = "CREATE TABLE IF NOT EXISTS samples (t INTEGER PRIMARY KEY, data TEXT NOT NULL)"

    def __init__(self, path=":memory:", clock=time.time):
        """path: the SQLite file (":memory:" keeps it only while the server runs)."""
        self.path = path
        self.clock = clock
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute(self.SCHEMA)

    def add(self, snap):
        """Keep one sample (a dict of numbers, plus "version")."""
        t = int(self.clock())
        self.db.execute("INSERT OR REPLACE INTO samples (t, data) VALUES (?, ?)",
                        (t, json.dumps(snap, separators=(",", ":"))))

    def prune(self):
        self.db.execute("DELETE FROM samples WHERE t < ?", (int(self.clock()) - self.KEEP_DAYS * 86400,))

    def samples(self, since):
        rows = self.db.execute("SELECT t, data FROM samples WHERE t >= ? ORDER BY t", (since,))
        return [(t, json.loads(data)) for t, data in rows]

    def regions(self, seconds):
        """Each region over the last `seconds`, busiest first: [{"region",
        "players_avg" (over the samples while the server ran), "players_peak",
        "med", "p95" (typical and slow round trips, ms: each sample's, averaged
        by how many players said theirs), "slow_share" (of those, how many were
        over SLOW_MS), "delay_med", "delay_p95" (the drawing delay, the same
        way), "stalls_per_min" (stalls per minute of play), "stalling_share"
        (of the players in a match, how many stalled more than once a
        minute)}]."""
        rows = self.samples(int(self.clock()) - seconds)
        acc = {}
        for _, snap in rows:
            for region, g in (snap.get("regions") or {}).items():
                a = acc.setdefault(region, {"players": 0, "peak": 0, "known": 0, "med": 0.0, "p95": 0.0, "slow": 0,
                                            "dk": 0, "dmed": 0.0, "dp95": 0.0, "play_min": 0.0, "stalls": 0,
                                            "playing": 0, "stalling": 0})
                a["players"] += g.get("players", 0)
                a["peak"] = max(a["peak"], g.get("players", 0))
                k = g.get("known", 0)
                if k and g.get("med") is not None:
                    a["known"] += k
                    a["med"] += g["med"] * k
                    a["p95"] += g["p95"] * k
                    a["slow"] += g.get("slow", 0)
                dk = g.get("delay_known", 0)
                if dk and g.get("delay_med") is not None:
                    a["dk"] += dk
                    a["dmed"] += g["delay_med"] * dk
                    a["dp95"] += g["delay_p95"] * dk
                a["play_min"] += g.get("play_min", 0)
                a["stalls"] += g.get("stalls", 0)
                a["playing"] += g.get("playing", 0)
                a["stalling"] += g.get("stalling", 0)
        n = max(1, len(rows))
        out = [{"region": region, "players_avg": round(a["players"] / n, 2), "players_peak": a["peak"],
                "med": round(a["med"] / a["known"]) if a["known"] else None,
                "p95": round(a["p95"] / a["known"]) if a["known"] else None,
                "slow_share": round(a["slow"] / a["known"], 3) if a["known"] else None,
                "delay_med": round(a["dmed"] / a["dk"]) if a["dk"] else None,
                "delay_p95": round(a["dp95"] / a["dk"]) if a["dk"] else None,
                "stalls_per_min": round(a["stalls"] / a["play_min"], 2) if a["play_min"] else None,
                "stalling_share": round(a["stalling"] / a["playing"], 3) if a["playing"] else None}
               for region, a in acc.items()]
        return sorted(out, key=lambda r: -r["players_avg"])

    def series(self, seconds, points=240):
        """The last `seconds`, in at most `points` buckets of equal length:

            {"start": t, "step": seconds per bucket, "t": [bucket start...],
             "gauges": {name: {"avg": [...], "max": [...]}},
             "counts": {name: [how many in that bucket...]},
             "restarts": [t...], "deploys": [[t, version]...]}

        A bucket with no samples (the server was stopped) is None."""
        now = int(self.clock())
        step = max(self.SAMPLE_EVERY, math.ceil(seconds / points))
        n = math.ceil(seconds / step)
        start = now - n * step
        rows = self.samples(start - 2 * self.SAMPLE_EVERY)  # one before, for the first count
        t_out = [start + k * step for k in range(n)]
        gsum, gmax, gn, counts = {}, {}, [0] * n, {}
        restarts, deploys = [], []
        prev = None
        for t, snap in rows:
            restarted = prev is not None and snap.get("uptime_seconds", 0) < prev.get("uptime_seconds", 0)
            k = min((t - start) // step, n - 1)  # (a sample this very second is in the last)
            if 0 <= k < n:
                if restarted:
                    restarts.append(t)
                if prev is not None and snap.get("version") != prev.get("version"):
                    deploys.append([t, snap.get("version")])
                gn[k] += 1
            for name, v in snap.items():
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    continue
                if name.endswith("_total"):
                    if prev is None or not 0 <= k < n:
                        continue
                    before = prev.get(name)
                    # After a restart the counter began again at 0
                    d = v if restarted or not isinstance(before, (int, float)) or v < before else v - before
                    counts.setdefault(name, [None] * n)
                    counts[name][k] = (counts[name][k] or 0) + d
                elif 0 <= k < n:
                    gsum.setdefault(name, [0.0] * n)[k] += v
                    gmax.setdefault(name, [None] * n)
                    gmax[name][k] = v if gmax[name][k] is None else max(gmax[name][k], v)
            prev = snap
        gauges = {name: {"avg": [round(sums[k] / gn[k], 3) if gn[k] else None for k in range(n)],
                         "max": gmax[name]}
                  for name, sums in gsum.items()}
        for c in counts.values():
            for k in range(n):
                if gn[k] and c[k] is None:
                    c[k] = 0
        return {"start": start, "step": step, "t": t_out, "gauges": gauges, "counts": counts,
                "restarts": restarts, "deploys": deploys}


class Retention:
    """Who comes back: each browser's first day and the days it joined a
    room, so the /admin page can show D1/D7/D30 retention (of the people
    who first played on a day, how many played again 1, 7 and 30 days later).

    A browser is its random token (core.js), hashed with a secret salt kept
    in the database, so what's stored can't be used to play as anyone.
    Nothing else about the player is kept. Days are UTC. Rows older than
    KEEP_DAYS are deleted.

    "installed": the page was opened from the home screen (the web app),
    counted separately so you can see how many play that way."""

    KEEP_DAYS = 120
    SCHEMA = (
        "CREATE TABLE IF NOT EXISTS retention_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS retention_players (id TEXT PRIMARY KEY, first INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS retention_days (id TEXT NOT NULL, day INTEGER NOT NULL, "
        "installed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (id, day))",
        "CREATE INDEX IF NOT EXISTS retention_days_day ON retention_days (day)",
    )
    MARKS = (1, 7, 30)

    def __init__(self, db, clock=time.time):
        """db: a sqlite3 connection (History's, so it's the same file)."""
        self.db = db
        self.clock = clock
        for sql in self.SCHEMA:
            self.db.execute(sql)
        row = self.db.execute("SELECT v FROM retention_meta WHERE k = 'salt'").fetchone()
        if row is None:
            salt = secrets.token_hex(16)
            self.db.execute("INSERT OR IGNORE INTO retention_meta (k, v) VALUES ('salt', ?)", (salt,))
            row = self.db.execute("SELECT v FROM retention_meta WHERE k = 'salt'").fetchone()
        self.salt = row[0].encode()
        self.recent = set()  # (id, installed) already written today
        self.recent_day = None

    def today(self):
        return int(self.clock() // 86400)

    def _id(self, token):
        return hashlib.sha256(self.salt + str(token).encode()).hexdigest()[:20]

    def seen(self, token, installed=False):
        """Someone joined a room. Cheap to call often: one write a day each."""
        if not token:
            return
        day = self.today()
        pid = self._id(token)
        if day != self.recent_day or len(self.recent) > 100000:
            self.recent, self.recent_day = set(), day  # a new day (or a lot of people)
        key = (pid, bool(installed))
        if key in self.recent:
            return
        self.recent.add(key)
        self.db.execute("INSERT OR IGNORE INTO retention_players (id, first) VALUES (?, ?)", (pid, day))
        self.db.execute("INSERT INTO retention_days (id, day, installed) VALUES (?, ?, ?) "
                        "ON CONFLICT (id, day) DO UPDATE SET installed = max(installed, excluded.installed)",
                        (pid, day, int(bool(installed))))

    def prune(self):
        cut = self.today() - self.KEEP_DAYS
        self.db.execute("DELETE FROM retention_days WHERE day < ?", (cut,))
        self.db.execute("DELETE FROM retention_players WHERE first < ? AND id NOT IN "
                        "(SELECT id FROM retention_days)", (cut,))

    def _active(self, since, until=None, installed=False):
        until = self.today() if until is None else until
        sql = "SELECT COUNT(DISTINCT id) FROM retention_days WHERE day BETWEEN ? AND ?"
        if installed:
            sql += " AND installed = 1"
        return self.db.execute(sql, (since, until)).fetchone()[0]

    def report(self, days=30):
        """{"today": day, "dau", "wau", "mau", "installed_wau",
            "daily": [{"day", "active", "new", "installed"}...] (oldest first),
            "cohorts": [{"day", "new", "d1", "d7", "d30"}...] (newest first;
                        a mark is None until that day has come),
            "overall": {"d1": {"cohort", "back", "rate"}, ...} over the
                       cohorts in the last `days` that have reached that mark}"""
        today = self.today()
        start = today - days + 1
        daily = {d: {"day": d, "active": 0, "new": 0, "installed": 0} for d in range(start, today + 1)}
        for d, active, inst in self.db.execute(
                "SELECT day, COUNT(*), SUM(installed) FROM retention_days WHERE day >= ? GROUP BY day", (start,)):
            daily[d]["active"], daily[d]["installed"] = active, inst or 0
        for d, n in self.db.execute(
                "SELECT first, COUNT(*) FROM retention_players WHERE first >= ? GROUP BY first", (start,)):
            daily[d]["new"] = n
        back = {}  # (cohort day, mark) -> how many came back that day
        for mark in self.MARKS:
            rows = self.db.execute(
                "SELECT p.first, COUNT(*) FROM retention_players p JOIN retention_days a "
                "ON a.id = p.id AND a.day = p.first + ? WHERE p.first >= ? GROUP BY p.first",
                (mark, start - max(self.MARKS)))
            for d, n in rows:
                back[(d, mark)] = n
        cohorts, overall = [], {}
        for d in range(today, start - 1, -1):
            new = daily[d]["new"]
            row = {"day": d, "new": new}
            for mark in self.MARKS:
                row[f"d{mark}"] = back.get((d, mark), 0) if d + mark <= today else None
            cohorts.append(row)
        for mark in self.MARKS:
            ready = [c for c in cohorts if c[f"d{mark}"] is not None]
            size = sum(c["new"] for c in ready)
            came = sum(c[f"d{mark}"] for c in ready)
            overall[f"d{mark}"] = {"cohort": size, "back": came,
                                   "rate": round(came / size, 4) if size else None}
        return {
            "today": today,
            "dau": self._active(today),
            "wau": self._active(today - 6),
            "mau": self._active(today - 29),
            "installed_wau": self._active(today - 6, installed=True),
            "daily": list(daily.values()),
            "cohorts": cohorts,
            "overall": overall,
        }
