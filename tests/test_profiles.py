"""Profiles and match history (issue #37): the browser (static/profile.js)
and the server (profiles.py) follow the same rules, so a browser's profile
can be attached to an account later."""
import asyncio
import json
import random
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from bonk_game.server import profiles
from bonk_game.server.match import Match, summaries

NODE = shutil.which("node")
PROFILE_JS = Path(__file__).resolve().parent.parent / "bonk_game" / "server" / "static" / "profile.js"
needs_node = pytest.mark.skipif(NODE is None, reason="needs node")


def entry(rng, k, **extra):
    of = rng.randint(2, 10)
    place = rng.randint(1, of)
    return {"id": f"ABCD-{k}", "at": 1_800_000_000 + k * 600, "mode": rng.choice(["ffa", "teams", "lives", "crown"]),
            "map": rng.choice(["platform", "classic", "grand"]), "place": place, "of": of, "won": place == 1,
            "score": rng.choice([0, 1, 2.5, 30]), "kos": rng.randint(0, 6), "falls": rng.randint(0, 3),
            "deaths": rng.randint(0, 5), "best_hit": round(rng.uniform(0, 40), 3), "pickups": rng.randint(0, 4),
            "awards": rng.sample(["kos", "hit", "falls", "survivor", "pickups"], rng.randint(0, 2)),
            "players": of, "people": rng.randint(1, of), **extra}


def python_side(script):
    """What profiles.py makes of the same steps."""
    out = []
    a = profiles.empty("browser-a")
    b = profiles.empty("browser-b")
    for kind, x in script:
        if kind == "a":
            a = profiles.record(a, x)
        elif kind == "b":
            b = profiles.record(b, x)
        elif kind == "merge":
            a = profiles.merge(a, b)
        elif kind == "validate":
            out.append(profiles.validate(x))
        out.append(a)
    return out


def node_side(script):
    js = f"""
    const P = require({json.dumps(str(PROFILE_JS))});
    const script = JSON.parse(require("fs").readFileSync(0, "utf8"));
    let a = P.empty("browser-a"), b = P.empty("browser-b");
    const out = [];
    for (const [kind, x] of script) {{
      if (kind === "a") a = P.record(a, x);
      else if (kind === "b") b = P.record(b, x);
      else if (kind === "merge") a = P.merge(a, b);
      else if (kind === "validate") out.push(P.validate(x));
      out.push(a);
    }}
    console.log(JSON.stringify(out));
    """
    res = subprocess.run([NODE, "-e", js], input=json.dumps(script), capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def steps():
    rng = random.Random(4)
    script = [("a", entry(rng, k)) for k in range(30)]
    script += [("a", entry(rng, 3))]                     # the same match again (a reconnect)
    script += [("b", entry(rng, 100 + k)) for k in range(40)]
    script += [("merge", None), ("merge", None)]          # adding the same profile twice
    script += [("a", entry(rng, 200, best_hit=55.55, awards=["kos", "BAD key", 5], kos=5000, mode="<x>"))]
    junk = {"format": "bonk-profile", "id": "x" * 99, "name": "n" * 40, "color": 12, "own_color": "#ZZZZZZ", "pattern": 7,
            "merged": ["ok", 3, ""], "stats": {"matches": -5, "wins": 2.7, "best_hit": "big", "awards": {"kos": 2, "Bad": 1},
                                                 "modes": {"ffa": {"matches": 3, "wins": "x"}, "UP": {}}, "first_at": None},
            "history": [{"id": "h1", "at": 5, "won": "yes"}, {"id": "h1"}, {"nope": 1}, "str"]}
    script += [("validate", junk), ("validate", {"format": "other"}), ("validate", [1, 2])]
    return script


@needs_node
def test_the_browser_and_the_server_agree():
    script = steps()
    py, js = python_side(script), node_side(script)
    assert len(py) == len(js)
    for k, (a, b) in enumerate(zip(py, js)):
        assert a == b, (k, script[min(k, len(script) - 1)][0])


def test_history_and_totals_add_up():
    rng = random.Random(1)
    p = profiles.empty("me")
    es = [entry(rng, k) for k in range(60)]
    for e in es:
        p = profiles.record(p, e)
    p = profiles.record(p, es[-1])  # counted once
    s = p["stats"]
    assert s["matches"] == 60 and s["wins"] == sum(e["won"] for e in es)
    assert s["kos"] == sum(e["kos"] for e in es)
    assert sum(t["matches"] for t in s["modes"].values()) == 60
    assert s["awards"]["kos"] == sum("kos" in e["awards"] for e in es)
    assert len(p["history"]) == profiles.HISTORY and p["history"][0]["id"] == es[-1]["id"]
    assert (s["first_at"], s["last_at"]) == (es[0]["at"], es[-1]["at"])


def test_merging_another_browser_counts_once():
    rng = random.Random(2)
    a, b = profiles.empty("a"), profiles.empty("b")
    a = profiles.record(a, entry(rng, 1))
    for k in range(3):
        b = profiles.record(b, entry(rng, 10 + k))
    b = {**b, "name": "other"}
    m = profiles.merge(a, b)
    assert m["stats"]["matches"] == 4 and m["merged"] == ["b"] and m["name"] == a["name"]
    assert [h["id"] for h in m["history"]] == ["ABCD-12", "ABCD-11", "ABCD-10", "ABCD-1"]
    assert profiles.merge(m, b) is m                       # already in
    assert profiles.merge(a, {**a, "stats": {**a["stats"], "matches": 9}})["stats"]["matches"] == 9  # own backup
    assert profiles.validate(json.loads(json.dumps(m))) == m  # a saved file reads back the same


def test_results_say_how_each_player_did():
    np.random.seed(3)
    m = Match("classic", [{"kind": "bot:hard", "name": "a"}, {"kind": "bot:easy", "name": "b"},
                          {"kind": "bot:easy", "name": "c"}], 2)
    while not m.finished:
        m.tick()
    r = m.results()
    s = r["summaries"]
    assert r["map"] == "classic" and len(s) == 3
    w = r["winner"]
    assert s[w]["won"] and s[w]["place"] == 1 and all(not x["won"] for i, x in enumerate(s) if i != w)
    assert all(x["of"] == 3 and x["kos"] == st["kos"] for x, st in zip(s, r["stats"]))
    for a in r["awards"]:
        assert all(a["id"] in s[i]["awards"] for i in a["slots"])
    e = profiles.history_entry({**r, "slots": [{"kind": "human"}, {"kind": "bot:easy"}, {"kind": "bot:easy"}]},
                               0, "ABCD-1", 1_800_000_000, "classic")
    p = profiles.record(profiles.empty("me"), e)
    assert p["history"][0] == profiles.validate(p)["history"][0] and p["history"][0]["people"] == 1


def test_places_with_ties_and_teams():
    stats = [{"kos": 0, "falls": 0, "deaths": 0, "best_hit": 0}] * 4
    places = lambda res, teams=None: [(x["place"], x["won"]) for x in summaries({**res, "stats": stats, "awards": []}, teams)]
    assert places({"scores": [3, 1, 1, 0], "winner": 0}) == [(1, True), (2, False), (2, False), (4, False)]
    assert places({"scores": [2, 2, 0, 1], "winner": None}) == [(1, False), (1, False), (4, False), (3, False)]
    # Lives: the winner may not have the most lives left... they're first anyway
    assert places({"scores": [0, 2, 3, 0], "winner": 1}) == [(3, False), (1, True), (2, False), (3, False)]
    teams = [0, 1, 0, 1]
    assert places({"scores": [0] * 4, "winner": None, "winner_team": 1}, teams) == [(2, False), (1, True), (2, False), (1, True)]
    assert places({"scores": [0] * 4, "winner": None, "winner_team": None}, teams) == [(1, False)] * 4


def test_a_room_gives_each_match_an_id():
    from bonk_game.server.room import Room

    class Inbox:
        def __init__(self):
            self.msgs = []

        async def __call__(self, msg):
            self.msgs.append(json.loads(msg) if isinstance(msg, str) else msg)

    async def go():
        room = Room("WXYZ")
        inbox = Inbox()
        await room.join("a", "Ann", inbox)
        room.settings.update(map="classic", bots=["bot:hard"], first_to=1)
        await room.start()
        # (The task, not room.match: the results go out just after the
        # match is cleared, and they're what this waits for)
        await room.task
        return [m for m in inbox.msgs if m["type"] == "results"][0]
    res = asyncio.run(asyncio.wait_for(go(), 120))
    assert res["match_id"].startswith("WXYZ-") and res["at"] > 1_700_000_000
    assert res["summaries"][0]["of"] == 2


def test_the_page_knows_map_and_mode_names():
    pytest.importorskip("aiohttp")
    from bonk_game.server import web
    page = web.render_index("v1")
    names = json.loads(page.split('<script id="bonk-names" type="application/json">')[1].split("</script>")[0])
    assert names["maps"]["swing"] == "Sinking Swing" and names["modes"]["ffa"] == "Free-for-all"


def test_settings_are_kept_but_not_without_limit():
    p = profiles.empty("p1")
    p["prefs"] = {"volume": 0.5}
    assert profiles.validate(p)["prefs"] == {"volume": 0.5}
    p["prefs"] = {"junk": "x" * profiles.PREFS_MAX}
    assert profiles.validate(p)["prefs"] == {}
