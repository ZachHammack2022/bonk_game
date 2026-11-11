"""Limits that keep one person (or script) from hogging a public server.

All numbers can be changed with environment variables of the same name
(e.g. BONK_MAX_ROOMS=100).
"""
import os
import re
import time


def _env(name, default):
    try:
        return type(default)(os.environ.get(name, default))
    except ValueError:
        return default


MAX_ROOMS = _env("BONK_MAX_ROOMS", 500)                # rooms on the server at once
# Busy: past this many people online (players and watchers, every room), or
# when matches keep falling behind (BUSY_LATE late ticks in BUSY_WINDOW
# seconds), nobody new gets in: they're told the servers are busy and try
# again in BUSY_RETRY seconds. People already in a room stay, and can come
# back after a refresh. One small machine manages about 100 (README: "How
# much can one server take?")
MAX_PEOPLE = _env("BONK_MAX_PEOPLE", 100)
BUSY_LATE = _env("BONK_BUSY_LATE", 3)
BUSY_WINDOW = _env("BONK_BUSY_WINDOW", 30.0)
BUSY_RETRY = _env("BONK_BUSY_RETRY", 15)
ROOMS_PER_IP = _env("BONK_ROOMS_PER_IP", 10)           # new rooms per IP per minute
MAX_MEMBERS = _env("BONK_MAX_MEMBERS", 16)             # people in a room (players + watchers)
CONNECTIONS_PER_IP = _env("BONK_CONNECTIONS_PER_IP", 20)
MESSAGES_PER_SECOND = _env("BONK_MESSAGES_PER_SECOND", 60.0)  # per connection, sustained
MESSAGE_BURST = _env("BONK_MESSAGE_BURST", 120.0)
# A connection that keeps sending too fast (this many dropped messages) is closed
MAX_DROPPED = _env("BONK_MAX_DROPPED", 300)
# Compress WebSocket messages (permessage-deflate) for browsers that ask, as
# they all do: about 60% fewer bytes sent, for about a third more CPU
WS_COMPRESS = os.environ.get("BONK_WS_COMPRESS", "1") not in ("", "0", "false")
# Behind a proxy (Fly, Render, nginx...) the client's IP is in a header
TRUST_PROXY = os.environ.get("BONK_TRUST_PROXY", "") not in ("", "0", "false")


class TokenBucket:
    """Allows `rate` events per second on average, and bursts up to `burst`."""

    def __init__(self, rate, burst, clock=time.monotonic):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.clock = clock
        self.last = clock()

    def allow(self, cost=1.0):
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class PerKey:
    """One TokenBucket per key (an IP), forgotten once it has refilled."""

    def __init__(self, rate, burst, clock=time.monotonic):
        self.rate, self.burst, self.clock = rate, burst, clock
        self.buckets = {}

    def allow(self, key):
        b = self.buckets.get(key)
        if b is None:
            b = self.buckets[key] = TokenBucket(self.rate, self.burst, self.clock)
        ok = b.allow()
        if len(self.buckets) > 10_000:
            self.sweep()
        return ok

    def sweep(self):
        now = self.clock()
        full = [k for k, b in self.buckets.items()
                if b.tokens + (now - b.last) * b.rate >= b.burst]
        for k in full:
            del self.buckets[k]


def client_region(request):
    """Where a connection came in: the Fly.io region that took it (the
    Fly-Region header, e.g. "lhr" for London), which is roughly where the
    player is. "direct" when not behind Fly's proxy."""
    if TRUST_PROXY:
        r = request.headers.get("Fly-Region", "").strip().lower()
        if re.fullmatch(r"[a-z0-9]{2,8}", r):
            return r
    return "direct"


def client_ip(request):
    if TRUST_PROXY:
        for header in ("Fly-Client-IP", "X-Real-IP"):
            if request.headers.get(header):
                return request.headers[header].strip()
        fwd = request.headers.get("X-Forwarded-For")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.remote or "?"
