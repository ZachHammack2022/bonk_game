"""Playtest reports (issue #32): what each browser saw during a match.

After every match each browser sends a "report": its ping, how often the
server's states arrived late, how far its own ball had to be corrected
(rubber-banding), its frame rate, what device it is and, if the player
picks one, how the match felt. Browsers also send JavaScript errors as they
happen ("client_error"). Both are logged (event "playtest" or
"client_error") and the last REPORTS_KEPT are kept in memory for
GET /api/playtest.

    python -m bonk_game.server.playtest_report server.log
    python -m bonk_game.server.playtest_report https://bonk.example.com --token T

turns them into a Markdown write-up: one row per report and a list of
things to look at.

BONK_PLAYTEST=0 turns reports off (browsers then don't collect anything).
"""
import collections
import logging
import os
import time

from . import metrics

ENABLED = os.environ.get("BONK_PLAYTEST", "1") not in ("", "0", "false")
REPORTS_KEPT = 500
REPORT_EVERY = 10.0     # seconds: at most one report per person this often
ERRORS_PER_PERSON = 5   # client errors kept per person (per connection)

FEELS = ("smooth", "ok", "laggy", "unplayable")

# What a report may hold: section -> numeric fields
NUMBERS = {
    "ping": ("n", "min", "med", "p95", "max", "jitter"),
    "states": ("n", "late", "max_gap", "missed"),
    "corrections": ("n", "big", "huge", "max", "avg"),
    "frames": ("fps", "slow", "frozen"),  # frozen: % of frames with nothing new to draw
}
DEVICE_TEXT = {"ua": 160, "screen": 20, "net": 12}


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return None
    v = round(max(0.0, min(float(v), 1e6)), 1)
    return int(v) if v.is_integer() else v


def _text(v, n):
    return str(v)[:n].replace("\n", " ").strip() if isinstance(v, str) else ""


def clean_report(msg):
    """Only the fields we know about, numbers clamped and text cut short."""
    out = {}
    for section, keys in NUMBERS.items():
        part = msg.get(section)
        if isinstance(part, dict):
            out[section] = {k: _num(part.get(k)) for k in keys if _num(part.get(k)) is not None}
    for k in ("seconds", "reconnects"):
        if _num(msg.get(k)) is not None:
            out[k] = _num(msg.get(k))
    dev = msg.get("device")
    if isinstance(dev, dict):
        d = {k: _text(dev.get(k), n) for k, n in DEVICE_TEXT.items() if _text(dev.get(k), n)}
        for k in ("touch", "pad"):
            if isinstance(dev.get(k), bool):
                d[k] = dev[k]
        out["device"] = d
    out["watching"] = msg.get("watching") is True
    out["predict"] = msg.get("predict") is not False
    out["lag"] = _num(msg.get("lag")) or 0  # a pretend network (netsim.js), if testing with one
    if _text(msg.get("sim"), 100):
        out["sim"] = _text(msg.get("sim"), 100)
    if msg.get("feel") in FEELS:
        out["feel"] = msg["feel"]
    note = _text(msg.get("note"), 500)
    if note:
        out["note"] = note
    return out


def clean_error(msg):
    return {"message": _text(msg.get("message"), 300) or "?",
            "where": _text(msg.get("where"), 120)}


class Reports:
    """The latest reports and client errors, newest last."""

    def __init__(self, keep=REPORTS_KEPT, clock=time.time):
        self.items = collections.deque(maxlen=keep)
        self.clock = clock
        self.reports = 0
        self.client_errors = 0

    def add(self, event, fields):
        t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock()))
        self.items.append({"t": t, "event": event, **fields})
        if event == "playtest":
            self.reports += 1
            metrics.event("playtest", **fields)
        else:
            self.client_errors += 1
            metrics.event("client_error", logging.WARNING, **fields)


REPORTS = Reports()
