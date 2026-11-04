"""What the server is doing, for whoever runs it: structured logs and the
numbers behind /metrics.

Logs are one JSON object per line on stderr, e.g.
    {"t": "2026-11-03T18:00:00Z", "event": "match_started", "room": "ABCD", ...}
so a host's log viewer can search and filter them.
"""
import collections
import datetime
import json
import logging
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
            "rooms_public": sum(1 for r in all_rooms if r.settings.get("public")),
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
