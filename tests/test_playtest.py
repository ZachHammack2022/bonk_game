"""Playtesting a hosted server (issue #32): browsers report what they saw
after each match, the server keeps the reports, a tool writes them up, and
a smoke test checks a deployed server end to end."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from bonk_game.server import playtest, playtest_report, smoke, web  # noqa: E402
from bonk_game.server.room import Room, RoomManager  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class Inbox:
    def __init__(self):
        self.msgs = []

    async def __call__(self, msg):
        self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)


@pytest.fixture(autouse=True)
def fresh_reports(monkeypatch):
    monkeypatch.setattr(playtest, "REPORTS", playtest.Reports())
    monkeypatch.setattr(playtest, "ENABLED", True)


def report(**extra):
    return {"type": "report", "seconds": 60, "reconnects": 0,
            "ping": {"n": 30, "min": 20, "med": 30, "p95": 45, "max": 60, "jitter": 4},
            "states": {"n": 1800, "late": 2, "max_gap": 120, "missed": 0},
            "corrections": {"n": 1700, "big": 1, "huge": 0, "max": 8, "avg": 0.6},
            "frames": {"fps": 60, "slow": 3},
            "device": {"ua": "Mozilla/5.0 (Windows NT 10.0) Chrome/150.0 Safari/537.36",
                       "screen": "1920x1080", "net": "4g", "touch": False, "pad": True},
            **extra}


PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) Version/19.0 Mobile/15E148 Safari/604.1"


def test_reports_keep_only_what_they_should():
    r = playtest.clean_report(report(
        feel="laggy", note="x" * 900 + "\nmore", extra="dropped", lag=150, predict=False,
        ping={"n": 3, "med": "fast", "p95": float("nan"), "max": 1e12, "min": True, "evil": 1},
        device={"ua": "u" * 400, "touch": "yes", "net": 4}))
    assert r["ping"] == {"n": 3, "max": 1e6}
    assert len(r["note"]) == 500 and r["feel"] == "laggy"
    assert r["device"] == {"ua": "u" * 160}
    assert r["lag"] == 150 and r["predict"] is False and "extra" not in r
    assert "feel" not in playtest.clean_report({"feel": "great"})


def test_reports_keep_how_far_behind_the_match_was_drawn():
    r = playtest.clean_report(report(frames={"fps": 60, "slow": 1, "frozen": 0.4, "guessed": 1.25, "delay": 107.33}))
    assert r["frames"] == {"fps": 60, "slow": 1, "frozen": 0.4, "guessed": 1.2, "delay": 107.3}
    md = playtest_report.summarize([{**r, "event": "playtest", "t": "2026-11-03T12:00:00", "name": "A"}])
    assert "drawn behind" in md and "107 ms" in md


def test_the_room_logs_reports_with_where_they_came_from(caplog):
    async def go():
        room = Room("ABCD")
        await room.join("a", "Ann", Inbox())
        room.results = {"slots": [{"kind": "human", "id": "a"}, {"kind": "bot:easy", "id": None}]}
        await room.handle("a", report(feel="smooth"))
        await room.handle("a", report())          # too soon after the last one: ignored
        for k in range(8):
            await room.handle("a", {"type": "client_error", "message": f"boom {k}", "where": "draw.js:1"})
        await room.handle("nobody", report())
        return list(playtest.REPORTS.items)
    with caplog.at_level("INFO", logger="bonk"):
        items = asyncio.run(go())
    reports = [i for i in items if i["event"] == "playtest"]
    errors = [i for i in items if i["event"] == "client_error"]
    assert len(reports) == 1 and len(errors) == playtest.ERRORS_PER_PERSON
    r = reports[0]
    assert (r["room"], r["name"], r["map"], r["mode"], r["players"], r["people"], r["feel"]) == \
        ("ABCD", "Ann", "swing", "ffa", 2, 1, "smooth")
    logged = [json.loads(rec.getMessage()) for rec in caplog.records]
    assert [e["event"] for e in logged].count("playtest") == 1
    assert any(e["event"] == "client_error" and e["message"] == "boom 0" for e in logged)


def test_reports_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(playtest, "ENABLED", False)

    async def go():
        room = Room("ABCD")
        inbox = Inbox()
        await room.join("a", "Ann", inbox)
        await room.handle("a", report())
        return inbox.msgs[0]
    welcome = asyncio.run(go())
    assert welcome["playtest"] is False and not playtest.REPORTS.items


def test_the_server_hands_out_reports_and_counts_them(monkeypatch):
    async def go():
        client = TestClient(TestServer(web.make_app(RoomManager())))
        await client.start_server()
        try:
            code = (await (await client.post("/api/rooms", json={"password": False})).json())["room"]
            ws = await client.ws_connect(f"/ws/{code}")
            await ws.send_json({"type": "hello", "name": "Ann", "token": "t", "version": web.VERSION})
            assert (await ws.receive_json())["playtest"] is True
            await ws.send_json(report(note="felt fine"))
            await ws.send_json({"type": "client_error", "message": "oops", "where": "x.js:1"})
            await ws.send_json({"type": "ping", "t": 1})
            while (await ws.receive_json())["type"] != "pong":
                pass
            await ws.close()
            items = (await (await client.get("/api/playtest")).json())["items"]
            snap = await (await client.get("/metrics?format=json")).json()
            monkeypatch.setattr(web, "METRICS_TOKEN", "s3cret")
            locked = (await client.get("/api/playtest")).status
            opened = (await client.get("/api/playtest", headers={"Authorization": "Bearer s3cret"})).status
            return items, snap, locked, opened
        finally:
            await client.close()
    items, snap, locked, opened = asyncio.run(go())
    assert [i["event"] for i in items] == ["playtest", "client_error"]
    assert items[0]["note"] == "felt fine" and items[0]["t"].endswith("Z")
    assert snap["playtest_reports_total"] == 1 and snap["client_errors_total"] == 1
    assert (locked, opened) == (401, 200)


def records():
    good = {"event": "playtest", "t": "2026-11-03T20:01:00Z", "room": "ABCD", "name": "Ann",
            "map": "classic", "mode": "ffa", **playtest.clean_report(report(feel="smooth"))}
    phone = {**good, "t": "2026-11-03T20:02:00Z", "name": "Bob",
             **playtest.clean_report(report(
                 feel="laggy", note="jumps | stutters", reconnects=1,
                 ping={"n": 30, "med": 140, "p95": 260, "jitter": 45},
                 states={"n": 1700, "late": 40, "max_gap": 900, "missed": 2},
                 corrections={"n": 1600, "big": 30, "huge": 4, "max": 55},
                 frames={"fps": 38, "slow": 90},
                 device={"ua": PHONE, "net": "3g", "touch": True}))}
    return [good, phone,
            {"event": "client_error", "t": "2026-11-03T20:02:01Z", "message": "x is undefined", "where": "draw.js:9"},
            {"event": "client_error", "t": "2026-11-03T20:02:02Z", "message": "x is undefined", "where": "draw.js:9"},
            {"event": "error", "t": "2026-11-03T20:03:00Z", "where": "match", "error": "KeyError('a')"},
            {"event": "match_ended", "t": "2026-11-03T20:00:59Z", "why": "won"}]


def test_the_write_up_points_at_what_went_wrong():
    md = playtest_report.summarize(records())
    assert "2 reports from 2 people in 1 rooms" in md and "1 matches ended: 1 won" in md
    look = md.split("## Things to look at")[1].split("## Reports")[0]
    assert "Ann" not in look  # nothing wrong there
    bob = next(line for line in look.splitlines() if "Bob" in line)
    for words in ("phone, Safari, 3g", "high ping (260 ms p95)", "jittery", "late (40/min",
                  "2 changes", "rubber-banding (30", "4 corrections over 20 px (worst 55 px)",
                  "low frame rate (38 fps)", "stutter", "lost connection 1×", "felt laggy"):
        assert words in bob, words
    assert "| phone | 1 | 140 ms | 30.0 | 38 |" in md and "| desktop | 1 | 30 ms |" in md
    assert "1 smooth, 1 laggy" in md and "jumps \\| stutters" in md
    assert "browser, 2×: `x is undefined` at draw.js:9" in md and "server (match), 1×: `KeyError('a')`" in md


def test_the_write_up_reads_host_logs(tmp_path):
    log = tmp_path / "fly.log"
    lines = ["bonk server on http://0.0.0.0:8000",
             *(f"2026-11-03T20:01:00Z app[e286] iad [info]{json.dumps(r)}" for r in records()),
             "{not json", '{"event": "room_created"}']
    log.write_text("\n".join(lines))
    out = subprocess.run([sys.executable, "-m", "bonk_game.server.playtest_report", str(log)],
                         capture_output=True, text=True, check=True, cwd=ROOT).stdout
    assert out == playtest_report.summarize(sorted(records(), key=lambda r: r["t"])) + "\n"
    assert "Nothing over the limits" in playtest_report.summarize(records()[:1])
    assert "No playtest reports" in playtest_report.summarize([])


def test_smoke_test_checks_a_running_server():
    async def go():
        server = TestServer(web.make_app(RoomManager()))
        await server.start_server()
        try:
            said = []
            r = await smoke.smoke(str(server.make_url("/")), seconds=1.5, out=said.append)
        finally:
            await server.close()
        return r, said
    r, said = asyncio.run(go())
    assert r["states_per_second"] > 20 and r["ping_med"] < 100
    assert any("compressed" in s for s in said)
    with pytest.raises(OSError):  # (nothing listening there)
        asyncio.run(smoke.smoke("http://127.0.0.1:9", seconds=0.5, out=lambda s: None))


def test_fly_config_matches_the_server():
    fly = (ROOT / "fly.toml").read_text()
    for line in ('internal_port = 8000', 'kill_signal = "SIGTERM"', 'BONK_TRUST_PROXY = "1"',
                 'path = "/healthz"', 'force_https = true'):
        assert line in fly, line
    import re
    timeout = int(re.search(r"kill_timeout = (\d+)", fly).group(1))
    assert web.DRAIN_SECONDS < timeout <= 300  # Fly allows up to 5 minutes
    script = (ROOT / "deploy" / "fly.sh").read_text()
    assert "--ha=false" in script and "scale count 1" in script
