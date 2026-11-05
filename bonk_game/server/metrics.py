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
import json
import logging
import math
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
        }


def prometheus(snap):
    """The same numbers in Prometheus' text format (counters end in _total)."""
    lines = []
    for k, v in snap.items():
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
