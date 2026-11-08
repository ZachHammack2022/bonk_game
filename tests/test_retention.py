"""Who comes back (metrics.Retention, on /admin) and the web app you add to
your home screen (manifest, icons)."""
import asyncio
import json
import os

import pytest

# (The server's packages: not in the training-only install, tests.yml)
pytest.importorskip("aiohttp")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from bonk_game.server import metrics, web  # noqa: E402
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


# --- ping by region (metrics.ping_by_region, History.regions, /admin) ---
def test_ping_is_summed_up_by_region_and_over_time():
    from bonk_game.server import room as room_mod

    class FakeRoom:
        def __init__(self, members):
            self.members = {k: m for k, m in enumerate(members)}

    def member(region, rtt, connected=True):
        m = room_mod.Member(f"t{region}{rtt}", "x", None)
        m.region, m.rtt, m.connected = region, rtt, connected
        return m

    rooms = [FakeRoom([member("lhr", 90), member("lhr", 110), member("iad", 20)]),
             FakeRoom([member("lhr", 300), member("iad", None), member("sin", 250, connected=False)])]
    regions = metrics.ping_by_region(rooms)
    assert set(regions) == {"lhr", "iad"}  # (sin's not connected)
    assert {k: regions["lhr"][k] for k in ("players", "known", "med", "p95", "slow")} == \
        {"players": 3, "known": 3, "med": 110, "p95": 300, "slow": 1}
    assert regions["lhr"]["play_min"] == 0 and regions["lhr"]["delay_med"] is None  # (nobody in a match)
    assert regions["iad"]["players"] == 2 and regions["iad"]["known"] == 1 and regions["iad"]["med"] == 20

    clock = Clock()
    h = metrics.History(clock=clock)
    h.add({"uptime_seconds": 1, "regions": regions})
    clock.t += 60
    h.add({"uptime_seconds": 61, "regions": {"lhr": {"players": 1, "known": 1, "med": 50, "p95": 50, "slow": 0}}})
    rows = h.regions(3600)
    assert [r["region"] for r in rows] == ["lhr", "iad"]
    lhr = rows[0]
    assert lhr["players_avg"] == 2 and lhr["players_peak"] == 3
    assert lhr["med"] == round((110 * 3 + 50) / 4) and lhr["slow_share"] == 0.25
    # Prometheus gets the numbers, not the table
    text = metrics.prometheus({"ping_med_ms": 40, "ping_p95_ms": None, "regions": regions})
    assert "bonk_ping_med_ms 40" in text and "regions" not in text and "p95" not in text


def test_a_players_region_and_ping_reach_admin(monkeypatch):
    from bonk_game.server import limits
    monkeypatch.setattr(web, "METRICS_TOKEN", "s3cret")
    monkeypatch.setattr(limits, "TRUST_PROXY", True)

    async def go(client):
        ws = await client.ws_connect("/ws/ABCD", headers={"Fly-Region": "LHR"})
        await ws.send_json({"type": "hello", "name": "Ann", "token": "t1", "version": web.VERSION, "reopen": True})
        assert (await ws.receive_json())["type"] == "welcome"
        await ws.send_json({"type": "ping", "t": 1, "rtt": 123})
        while (await ws.receive_json())["type"] != "pong":
            pass
        bad = await client.ws_connect("/ws/ABCD", headers={"Fly-Region": "<script>"})
        await bad.send_json({"type": "hello", "name": "Bo", "token": "t2", "version": web.VERSION})
        assert (await bad.receive_json())["type"] == "welcome"
        await bad.send_json({"type": "ping", "t": 1, "rtt": "fast"})  # (ignored)
        while (await bad.receive_json())["type"] != "pong":
            pass
        body = await (await client.get("/api/admin/metrics", headers={"Authorization": "Bearer s3cret"})).json()
        regions = body["now"]["regions"]
        assert {k: regions["lhr"][k] for k in ("players", "known", "med", "p95", "slow")} == \
            {"players": 1, "known": 1, "med": 123, "p95": 123, "slow": 0}
        assert regions["direct"]["players"] == 1 and regions["direct"]["known"] == 0
        assert body["now"]["ping_med_ms"] == 123
        assert isinstance(body["regions"], list)
        assert "bonk_ping_med_ms 123" in await (await client.get("/metrics", headers={"Authorization": "Bearer s3cret"})).text()
    asyncio.run(with_client(go))


# --- stalls (Member.note_network, ping_by_region, History.regions, /admin) ---
def test_a_ping_says_how_smoothly_states_come():
    """In a match, each ping says the drawing delay and how many states came
    since the last (and how many after a stall); kept for a minute. Nonsense
    is ignored, and stalls can't be more than states."""
    from bonk_game.server import room as room_mod
    m = room_mod.Member("t", "x", None)
    m.note_network(100.0, {"rtt": 80, "delay": 42.4, "states": 30, "stalls": 1})
    assert (m.rtt, m.delay) == (80, 42)
    m.note_network(101.0, {"rtt": "fast", "delay": -5, "states": 29, "stalls": 99})
    assert m.rtt == 80 and m.delay is None  # (kept / not sensible)
    assert m.stall_window(101.0) == (59, 30)  # (stalls capped at that ping's states)
    for bad in ({"states": True, "stalls": 1}, {"states": "30"}, {"states": 5000}, {"states": -1}, {}):
        m.note_network(102.0, bad)
    assert m.stall_window(102.0) == (59, 30) and m.delay is None  # (and no states: not in a match now)
    assert m.stall_window(160.5) == (29, 29)  # (older than a minute: gone)
    assert m.stall_window(500.0) == (0, 0)


def test_stalls_are_summed_up_by_region_and_over_time():
    from bonk_game.server import room as room_mod

    class FakeRoom:
        def __init__(self, members):
            self.members = {k: m for k, m in enumerate(members)}

    def player(region, per_second, stalls_in_all, delay):
        """In a match a whole minute: per_second states each ping, with
        stalls_in_all stalls over the minute."""
        m = room_mod.Member(f"t{region}{delay}", "x", None)
        m.region = region
        for k in range(60):
            m.note_network(float(k), {"rtt": 50, "delay": delay, "states": per_second,
                                      "stalls": 1 if k < stalls_in_all else 0})
        return m

    lobby = room_mod.Member("tlobby", "x", None)
    lobby.region = "lhr"
    lobby.note_network(59.0, {"rtt": 50})
    rooms = [FakeRoom([player("lhr", 30, 0, 40), player("lhr", 30, 6, 90), lobby]),
             FakeRoom([player("iad", 30, 1, 35), player("iad", 4, 3, 200)])]  # (4 a second: under 10 s of play, not "playing")
    r = metrics.ping_by_region(rooms, now=59.0)
    lhr, iad = r["lhr"], r["iad"]
    assert lhr["players"] == 3 and lhr["delay_known"] == 2 and lhr["delay_med"] == 90 and lhr["delay_p95"] == 90
    assert lhr["play_min"] == 2.0 and lhr["stalls"] == 6 and lhr["playing"] == 2 and lhr["stalling"] == 1
    assert iad["playing"] == 1 and iad["stalling"] == 0 and iad["stalls"] == 4
    # One stall isn't "often", even in under a minute of play
    once = room_mod.Member("tonce", "x", None)
    for k in range(40):
        once.note_network(float(k), {"states": 30, "stalls": 1 if k == 5 else 0})
    assert metrics.ping_by_region([FakeRoom([once])], now=39.0)["direct"]["stalling"] == 0
    assert iad["play_min"] == round((30 * 60 + 4 * 60) / 1800, 3)

    clock = Clock()
    h = metrics.History(clock=clock)
    h.add({"uptime_seconds": 1, "regions": r})
    clock.t += 60
    h.add({"uptime_seconds": 61, "regions": {"lhr": {**lhr, "delay_known": 1, "delay_med": 30, "delay_p95": 30,
                                                     "play_min": 1.0, "stalls": 0, "playing": 1, "stalling": 0}}})
    rows = {row["region"]: row for row in h.regions(3600)}
    assert rows["lhr"]["delay_med"] == round((90 * 2 + 30) / 3)
    assert rows["lhr"]["stalls_per_min"] == 2.0 and rows["lhr"]["stalling_share"] == round(1 / 3, 3)
    # (an old sample from before stalls were counted adds nothing to them)
    clock.t += 60
    h.add({"uptime_seconds": 121, "regions": {"lhr": {"players": 1, "known": 1, "med": 50, "p95": 50, "slow": 0}}})
    assert {row["region"]: row for row in h.regions(3600)}["lhr"]["stalls_per_min"] == 2.0


def test_stalls_reach_admin(monkeypatch):
    monkeypatch.setattr(web, "METRICS_TOKEN", "s3cret")

    async def go(client):
        ws = await client.ws_connect("/ws/ABCD")
        await ws.send_json({"type": "hello", "name": "Ann", "token": "t1", "version": web.VERSION, "reopen": True})
        assert (await ws.receive_json())["type"] == "welcome"
        for _ in range(12):
            await ws.send_json({"type": "ping", "t": 1, "rtt": 60, "delay": 55, "states": 30, "stalls": 1})
            while (await ws.receive_json())["type"] != "pong":
                pass
        body = await (await client.get("/api/admin/metrics", headers={"Authorization": "Bearer s3cret"})).json()
        g = body["now"]["regions"]["direct"]
        assert g["delay_med"] == 55 and g["stalls"] == 12 and g["playing"] == 1 and g["stalling"] == 1
        assert body["now"]["delay_med_ms"] == 55 and body["now"]["stalls_per_min"] == 60.0
        text = await (await client.get("/metrics", headers={"Authorization": "Bearer s3cret"})).text()
        assert "bonk_delay_med_ms 55" in text and "bonk_stalls_per_min 60.0" in text
    asyncio.run(with_client(go))
