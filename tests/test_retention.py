"""Who comes back (metrics.Retention, on /admin) and the web app you add to
your home screen (manifest, icons)."""
import asyncio
import json
import os

from aiohttp.test_utils import TestClient, TestServer

from bonk_game.server import metrics, web
from bonk_game.server.room import RoomManager

DAY = 86400
STATIC = os.path.join(os.path.dirname(web.__file__), "static")


class Clock:
    def __init__(self, t=20_000 * DAY + 3600):
        self.t = t

    def __call__(self):
        return self.t


def retention(clock=None, path=":memory:"):
    clock = clock or Clock()
    return metrics.Retention(metrics.History(path, clock=clock).db, clock=clock), clock


def test_d1_d7_d30_count_who_came_back_on_that_day():
    r, clock = retention()
    first = clock.t
    for k in range(10):
        r.seen(f"tok{k}")
    r.seen("tok0")  # (twice the same day is once)
    for day, back in [(1, range(4)), (2, range(8)), (7, range(2)), (30, range(1))]:
        clock.t = first + day * DAY
        for k in back:
            r.seen(f"tok{k}")
    clock.t = first + 30 * DAY
    rep = r.report(days=31)
    start = rep["cohorts"][-1]
    assert start["new"] == 10 and (start["d1"], start["d7"], start["d30"]) == (4, 2, 1)
    assert rep["overall"]["d1"] == {"cohort": 10, "back": 4, "rate": 0.4}
    assert rep["overall"]["d7"]["rate"] == 0.2 and rep["overall"]["d30"]["rate"] == 0.1
    assert rep["dau"] == 1 and rep["mau"] == 8  # (days 1-30: everyone back on day 2)


def test_a_mark_that_hasnt_come_yet_is_none_not_zero():
    r, clock = retention()
    r.seen("a")
    clock.t += DAY
    r.seen("b")
    rep = r.report()
    today, yesterday = rep["cohorts"][0], rep["cohorts"][1]
    assert today["new"] == 1 and today["d1"] is None
    assert yesterday["d1"] == 0 and yesterday["d7"] is None
    assert rep["overall"]["d1"] == {"cohort": 1, "back": 0, "rate": 0.0}
    assert rep["overall"]["d7"] == {"cohort": 0, "back": 0, "rate": None}
    assert [d["new"] for d in rep["daily"][-2:]] == [1, 1]
    assert rep["wau"] == 2 and rep["dau"] == 1


def test_installed_players_are_counted_and_tokens_are_never_stored(tmp_path):
    path = str(tmp_path / "m.db")
    r, clock = retention(path=path)
    r.seen("secret-token", installed=False)
    r.seen("secret-token", installed=True)  # opened from the home screen later that day
    r.seen("other")
    rep = r.report()
    assert rep["installed_wau"] == 1 and rep["daily"][-1]["installed"] == 1
    assert rep["daily"][-1]["active"] == 2
    raw = open(path, "rb").read() + open(path + "-wal", "rb").read() if os.path.exists(path + "-wal") \
        else open(path, "rb").read()
    assert b"secret-token" not in raw
    # The salt is kept, so the same browser is the same player after a restart
    again, _ = retention(clock, path)
    assert again.salt == r.salt
    again.seen("secret-token")
    assert again.report()["cohorts"][0]["new"] == 2


def test_old_days_are_forgotten():
    r, clock = retention()
    r.seen("old")
    clock.t += (r.KEEP_DAYS + 1) * DAY
    r.seen("new")
    r.prune()
    assert r.db.execute("SELECT COUNT(*) FROM retention_players").fetchone()[0] == 1
    assert r.db.execute("SELECT COUNT(*) FROM retention_days").fetchone()[0] == 1


async def with_client(go):
    client = TestClient(TestServer(web.make_app(RoomManager())))
    await client.start_server()
    try:
        return await go(client)
    finally:
        await client.close()


def test_joining_a_room_counts_and_admin_shows_retention(monkeypatch):
    monkeypatch.setattr(web, "METRICS_TOKEN", "s3cret")

    async def go(client):
        for token, installed in [("t1", False), ("t2", True)]:
            ws = await client.ws_connect("/ws/ABCD")
            await ws.send_json({"type": "hello", "name": "Ann", "token": token, "version": web.VERSION,
                                "installed": installed, "reopen": True})
            got = await ws.receive_json()
            assert got["type"] == "welcome", got
            await ws.close()
        body = await (await client.get("/api/admin/metrics", headers={"Authorization": "Bearer s3cret"})).json()
        ret = body["retention"]
        assert ret["dau"] == 2 and ret["installed_wau"] == 1 and ret["cohorts"][0]["new"] == 2
        page = await (await client.get("/admin")).text()
        assert "Who comes back" in page
    asyncio.run(with_client(go))


def test_the_web_app_manifest_and_icons():
    async def go(client):
        r = await client.get("/manifest.webmanifest")
        assert r.status == 200 and r.content_type == "application/manifest+json"
        m = json.loads(await r.text())
        assert m["start_url"] == "/" and m["scope"] == "/" and m["display"] in ("fullscreen", "standalone")
        assert {i["sizes"] for i in m["icons"]} >= {"192x192", "512x512"}
        assert any(i.get("purpose") == "maskable" for i in m["icons"])
        for icon in m["icons"]:
            got = await client.get(icon["src"])
            assert got.status == 200 and (await got.read())[:8] == b"\x89PNG\r\n\x1a\n"
        page = await (await client.get("/")).text()
        assert 'rel="manifest" href="/manifest.webmanifest"' in page
        assert 'rel="apple-touch-icon"' in page and 'id="install"' in page
        assert (await client.get("/static/icons/apple-touch-icon.png")).status == 200
    asyncio.run(with_client(go))
