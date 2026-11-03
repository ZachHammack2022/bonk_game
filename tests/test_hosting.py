"""Running the server for real (issue #30): client versions, cache busting,
/metrics, logs and restarting without dropping matches."""
import asyncio
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time

import pytest

aiohttp = pytest.importorskip("aiohttp")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from bonk_game.server import metrics, room as room_mod, web  # noqa: E402
from bonk_game.server.room import Room, RoomManager, ServerFull  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(coro):
    return asyncio.run(coro)


class Inbox:
    def __init__(self):
        self.msgs = []

    async def __call__(self, msg):
        self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)

    def kinds(self):
        return [m["type"] for m in self.msgs]


def hello(**extra):
    return {"type": "hello", "name": "Ann", "token": "tok-a", "version": web.VERSION, **extra}


async def with_client(go, rooms=None):
    client = TestClient(TestServer(web.make_app(rooms or RoomManager())))
    await client.start_server()
    try:
        return await go(client)
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Versions and caching
# ---------------------------------------------------------------------------
def test_the_page_asks_for_this_versions_files():
    page = web.render_index("abc123")
    urls = re.findall(r'(?:src|href)="(/static/[^"]+)"', page)
    assert len(urls) > 5 and all(u.endswith("?v=abc123") for u in urls)
    assert '<meta name="bonk-version" content="abc123">' in page


def test_the_version_changes_with_any_client_file(tmp_path):
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "a.js").write_text("one")
    (tmp_path / "index.html").write_text("<head></head>")
    v1 = web.client_version(str(tmp_path))
    assert v1 == web.client_version(str(tmp_path))
    (tmp_path / "js" / "a.js").write_text("two")
    assert web.client_version(str(tmp_path)) != v1


def test_versioned_files_are_cached_for_good_and_the_page_never():
    async def go(client):
        r = await client.get("/")
        assert r.headers["Cache-Control"] == "no-cache"
        page = await r.text()
        src = re.search(r'<script src="([^"]+)"', page).group(1)
        assert src.endswith(f"?v={web.VERSION}")
        r = await client.get(src)
        assert r.status == 200 and "immutable" in r.headers["Cache-Control"]
        r = await client.get("/static/style.css?v=old")
        assert r.status == 200 and r.headers["Cache-Control"] == "no-cache"
    run(with_client(go))


@pytest.mark.parametrize("version", ["old", None])
def test_an_old_tab_is_told_to_refresh(version):
    async def go(client):
        code = (await (await client.post("/api/rooms")).json())["room"]
        ws = await client.ws_connect(f"/ws/{code}")
        msg = hello(version=version)
        if version is None:
            del msg["version"]
        before = metrics.STATS.refused_old_clients
        await ws.send_json(msg)
        err = await ws.receive_json()
        assert err["type"] == "error" and err["fatal"] and err["refresh"]
        assert "Refresh" in err["message"]
        assert metrics.STATS.refused_old_clients == before + 1
    run(with_client(go))


def test_coming_back_after_a_restart_reopens_the_room():
    async def go(client):
        ws = await client.ws_connect("/ws/ABCD")
        await ws.send_json(hello())  # a fresh page: the room is just gone
        assert "doesn't exist" in (await ws.receive_json())["message"]
        ws = await client.ws_connect("/ws/ABCD")
        await ws.send_json(hello(reopen=True))
        welcome = await ws.receive_json()
        assert welcome["type"] == "welcome" and welcome["room"] == "ABCD"
        lobby = await ws.receive_json()
        assert lobby["host"] == "tok-a"
        bad = await client.ws_connect("/ws/AB1D")  # not a code we'd make
        await bad.send_json(hello(reopen=True))
        assert (await bad.receive_json())["fatal"]
    run(with_client(go))


def test_the_old_host_gets_the_room_back_even_if_someone_beats_them_to_it():
    async def go(client):
        guest = await client.ws_connect("/ws/ABCD")
        await guest.send_json(hello(token="bob", reopen=True))
        await guest.receive_json()
        assert (await guest.receive_json())["host"] == "bob"
        host = await client.ws_connect("/ws/ABCD")
        await host.send_json(hello(token="ann", reopen=True, host=True))
        await host.receive_json()
        assert (await host.receive_json())["host"] == "ann"
        other = await client.ws_connect("/ws/ABCD")  # only once
        await other.send_json(hello(token="cat", reopen=True, host=True))
        await other.receive_json()
        assert (await other.receive_json())["host"] == "ann"
    run(with_client(go))


# ---------------------------------------------------------------------------
# /metrics and logs
# ---------------------------------------------------------------------------
def test_metrics_report_live_numbers(monkeypatch):
    monkeypatch.setattr(room_mod, "TICK_HZ", 600)

    async def go(client):
        code = (await (await client.post("/api/rooms")).json())["room"]
        ws = await client.ws_connect(f"/ws/{code}")
        await ws.send_json(hello())
        await ws.send_json({"type": "settings", "map": "classic", "first_to": 50,
                            "bots": ["bot:medium"] * 3})
        await ws.send_json({"type": "start"})
        states = 0
        while states < 60:
            if (await ws.receive_json())["type"] == "state":
                states += 1
        snap = await (await client.get("/metrics?format=json")).json()
        assert snap["rooms"] >= 1 and snap["members_connected"] >= 1
        assert snap["matches_running"] == 1 and snap["connections"] >= 1
        assert snap["tick_ms_avg"] > 0 and snap["tick_ms_p99"] >= snap["tick_ms_avg"]
        assert snap["bytes_sent_total"] > 0 and snap["version"] == web.VERSION
        text = await (await client.get("/metrics")).text()
        assert "# TYPE bonk_rooms gauge" in text and "bonk_bytes_sent_total " in text
        assert f'bonk_info{{version="{web.VERSION}"}} 1' in text
        for line in text.splitlines():
            assert line.startswith("#") or re.fullmatch(r'bonk_\w+(\{[^}]*\})? -?[\d.]+', line), line
    run(with_client(go))


def test_metrics_can_need_a_token(monkeypatch):
    monkeypatch.setattr(web, "METRICS_TOKEN", "s3cret")

    async def go(client):
        assert (await client.get("/metrics")).status == 401
        assert (await client.get("/metrics", headers={"Authorization": "Bearer nope"})).status == 401
        r = await client.get("/metrics", headers={"Authorization": "Bearer s3cret"})
        assert r.status == 200
    run(with_client(go))


def test_tick_stats():
    s = metrics.Stats()
    assert s.tick_ms() == (0.0, 0.0)
    for k in range(100):
        s.tick(0.001 if k < 98 else 0.010)
    avg, p99 = s.tick_ms()
    assert avg == pytest.approx(1.18) and p99 == pytest.approx(10.0)


def test_rooms_and_matches_are_logged(monkeypatch, caplog):
    monkeypatch.setattr(room_mod, "TICK_HZ", 3000)
    caplog.set_level(logging.INFO, logger="bonk")
    monkeypatch.setattr(metrics.log, "propagate", True)  # (off when the server runs)

    async def go():
        rooms = RoomManager()
        room = rooms.create()
        await room.join("a", "Ann", Inbox())
        room.settings.update(map="classic", first_to=1, bots=["bot:hard"] * 3)
        await room.start()
        await room.task
    run(go())
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "bonk"]
    names = [e["event"] for e in events]
    assert names[:2] == ["room_created", "match_started"] and "match_ended" in names
    started = events[1]
    assert started["map"] == "classic" and started["people"] == 1 and started["bots"] == 3
    ended = next(e for e in events if e["event"] == "match_ended")
    assert ended["why"] == "finished" and max(ended["scores"]) == 1


def test_a_crash_in_a_match_is_logged_and_the_room_carries_on(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="bonk")
    monkeypatch.setattr(metrics.log, "propagate", True)

    async def go():
        room = Room("ABCD")
        inbox = Inbox()
        await room.join("a", "Ann", inbox)
        await room.start()
        monkeypatch.setattr(room.match, "tick", lambda: 1 / 0)
        await room.task
        assert room.match is None and room.results is None
        assert "Something went wrong" in [m for m in inbox.msgs if m["type"] == "error"][-1]["message"]
        assert inbox.msgs[-1]["type"] == "lobby"
    run(go())
    errors = [json.loads(r.getMessage()) for r in caplog.records
              if r.name == "bonk" and r.levelno == logging.ERROR]
    assert errors and "ZeroDivisionError" in errors[0]["error"]


# ---------------------------------------------------------------------------
# Restarting
# ---------------------------------------------------------------------------
def test_draining_lets_matches_finish_then_says_restart(monkeypatch):
    monkeypatch.setattr(room_mod, "TICK_HZ", 3000)

    async def go():
        rooms = RoomManager()
        playing, idle = rooms.create(), rooms.create()
        a, b = Inbox(), Inbox()
        await playing.join("a", "Ann", a)
        playing.settings.update(map="classic", first_to=1, bots=["bot:hard"] * 3)
        await playing.start()
        await idle.join("b", "Bob", b)
        await rooms.drain(timeout=60, poll=0.01)
        assert "results" in a.kinds()  # the match got to finish
        assert a.kinds().index("notice") < a.kinds().index("results") < a.kinds().index("restart")
        assert "notice" not in b.kinds() and b.kinds()[-1] == "restart"
        with pytest.raises(ServerFull):
            rooms.create()
        await playing.start()  # no new matches either
        assert playing.match is None and "restarting" in a.msgs[-1]["message"]
    run(go())


def test_draining_gives_up_on_a_match_that_runs_too_long():
    async def go():
        rooms = RoomManager()
        room = rooms.create()
        inbox = Inbox()
        await room.join("a", "Ann", inbox)
        room.settings["first_to"] = 100
        await room.start()
        t = time.monotonic()
        await rooms.drain(timeout=0.3, poll=0.01)
        assert time.monotonic() - t < 2
        await asyncio.sleep(0.01)
        assert room.match is None and inbox.kinds()[-1] == "restart"
    run(go())


def test_new_rooms_are_refused_while_draining():
    async def go(client):
        client.app[web.ROOMS].draining = True
        r = await client.post("/api/rooms")
        assert r.status == 503 and "restarting" in (await r.json())["error"]
    run(with_client(go))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM")
def test_sigterm_tells_everyone_and_exits_cleanly():
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": ROOT, "BONK_DRAIN_SECONDS": "5"}
    proc = subprocess.Popen([sys.executable, "-m", "bonk_game.server", "--host", "127.0.0.1",
                             "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    base = f"http://127.0.0.1:{port}"

    async def go():
        async with aiohttp.ClientSession() as http:
            for _ in range(100):
                try:
                    async with http.get(base + "/healthz") as r:
                        if r.status == 200:
                            break
                except aiohttp.ClientError:
                    await asyncio.sleep(0.1)
            async with http.post(base + "/api/rooms") as r:
                code = (await r.json())["room"]
            ws = await http.ws_connect(f"{base}/ws/{code}")
            await ws.send_json(hello())
            assert (await ws.receive_json())["type"] == "welcome"
            proc.send_signal(signal.SIGTERM)
            got = []
            while True:
                m = await ws.receive(timeout=10)
                if m.type != aiohttp.WSMsgType.TEXT:
                    break
                got.append(json.loads(m.data)["type"])
            assert "restart" in got
            assert ws.close_code == aiohttp.WSCloseCode.SERVICE_RESTART

    try:
        run(go())
        out, err = proc.communicate(timeout=15)
    finally:
        proc.kill()
    assert proc.returncode == 0, err
    events = [json.loads(line)["event"] for line in err.splitlines() if line.startswith("{")]
    assert events[0] == "server_started" and "draining" in events and events[-1] == "server_stopped"


def test_the_load_test_runs():
    from bonk_game.server import load_test
    r = asyncio.run(load_test.run_level(1, 0.5, "grand", "bots"))
    assert r["rooms"] == 1 and r["ticks_per_s"] > 20 and r["kb_per_s_room"] > 0
    assert "| 1 |" in load_test.table([r])
