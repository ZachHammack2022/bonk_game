"""Badges (badges.py, js/badges.js): goals with levels, from your stats, and
the match highlights (feats) some of them count."""
import json
import pathlib
import shutil
import subprocess

import numpy as np
import pytest

from bonk_game.server import badges, profiles
from bonk_game.server.match import MULTI_KO, TICK_HZ, Match, new_feats

BADGES_JS = pathlib.Path(__file__).resolve().parents[1] / "bonk_game" / "server" / "static" / "js" / "badges.js"
NODE = shutil.which("node")


def test_badges_are_well_made():
    ids = [b["id"] for b in badges.describe()]
    assert len(ids) == len(set(ids))
    stats = profiles.empty("x")["stats"]
    for b in badges.describe():
        assert 1 <= len(b["levels"]) <= len(badges.LEVELS), b["id"]
        assert b["levels"] == sorted(set(b["levels"])) and b["levels"][0] > 0, b["id"]
        assert "{n}" in b["goal"] and b["icon"] and b["title"]
        # Everything a badge counts is in a profile's stats (or a highlight)
        stat = b["stat"]
        known = {*new_feats(), "flawless", *profiles.DERIVED_FEATS, "giant_slayer", "bully", "rival"}
        assert stat.startswith("feats.") and stat[6:] in known or stat in stats, stat
        assert badges.level(stats, b) == 0  # (nobody starts with one)


def test_levels_follow_your_stats():
    p = profiles.empty("x")
    kos = next(b for b in badges.describe() if b["id"] == "kos")
    maps = next(b for b in badges.describe() if b["id"] == "maps")
    triple = next(b for b in badges.describe() if b["id"] == "triple")
    for k in range(30):
        p = profiles.record(p, {"id": f"m{k}", "at": 1_800_000_000 + k, "mode": "ffa",
                                "map": ["classic", "platform", "swing", "grand"][k % 4],
                                "won": k % 3 == 0, "kos": 1, "feats": {"triple": 1} if k == 7 else {}})
    s = p["stats"]
    assert s["kos"] == 30 and badges.level(s, kos) == 2  # (past 1 and 25, not 100)
    assert badges.level(s, maps) == 1                  # (4 maps: past 3, not 5)
    assert s["feats"] == {"triple": 1} and badges.level(s, triple) == 1


def ko(m, by, victim):
    """`by` knocks out `victim` now (what match.py does for a death)."""
    m.stats[by]["kos"] += 1
    m._feat_ko(by, victim)


def test_knockouts_make_highlights():
    m = Match("classic", [{"kind": "bot:easy", "name": n} for n in "abcd"], 3)
    ko(m, 1, 0)
    assert m.feats[1]["first_blood"] == 1  # (the match's first knockout)
    m.tick_count += int(MULTI_KO * TICK_HZ)  # (just in time)
    ko(m, 1, 2)
    assert m.feats[1]["double"] == 1 and m.feats[1]["triple"] == 0
    m.tick_count += 10
    ko(m, 1, 3)
    assert m.feats[1] == {"first_blood": 1, "double": 1, "triple": 1, "super_ko": 0}
    # Too slow: the next one starts a new run
    m.tick_count += int(MULTI_KO * TICK_HZ) + 1
    ko(m, 2, 1)
    m.tick_count += int(MULTI_KO * TICK_HZ) + 1
    ko(m, 2, 3)
    assert m.feats[2] == new_feats()  # (no first blood, no double)


def test_super_knockouts():
    m = Match("classic", [{"kind": "bot:easy", "name": n} for n in "abc"], 3, power_ups=True)
    m.powerups.effects[0] = ["giant", 100]  # (a super's on)
    ko(m, 0, 1)
    assert m.feats[0]["super_ko"] == 1
    # A bomb or a black hole: it counts even if the super's over by the time they're out
    m.powerups.effects[0] = None
    m.powerups.super_kos[2] = 0
    ko(m, 0, 2)
    assert m.feats[0]["super_ko"] == 2 and not m.powerups.super_kos
    ko(m, 0, 1)  # (an ordinary knockout)
    assert m.feats[0]["super_ko"] == 2


def test_a_match_reports_highlights_and_flawless_wins():
    np.random.seed(5)
    m = Match("classic", [{"kind": "bot:hard", "name": "a"}, {"kind": "bot:easy", "name": "b"}], 2)
    while not m.finished:
        m.tick()
    r = m.results()
    w = r["winner"]
    for i, s in enumerate(r["summaries"]):
        assert set(s["feats"]) == {*new_feats(), "flawless"}
        assert s["feats"]["flawless"] == (1 if i == w and r["stats"][i]["deaths"] == 0 else 0)
    assert sum(s["feats"]["first_blood"] for s in r["summaries"]) == (1 if any(st["kos"] for st in r["stats"]) else 0)


@pytest.mark.skipif(NODE is None, reason="needs node")
def test_the_page_works_out_the_same_levels():
    """js/badges.js and badges.py agree, and a match's report says what it earned."""
    defs = badges.describe()
    before = profiles.empty("x")["stats"]
    p = profiles.empty("x")
    for k in range(12):
        p = profiles.record(p, {"id": f"m{k}", "at": 1_800_000_000 + k, "mode": ["ffa", "teams", "lives"][k % 3],
                                "map": ["classic", "platform", "swing"][k % 3], "won": True, "kos": 3,
                                "best_hit": 16.5, "pickups": 1, "awards": ["kos"],
                                "feats": {"first_blood": 1, "double": 1, "flawless": 1}})
    after = p["stats"]
    js = f"""
    global.NAMES = {{ badges: {json.dumps(defs)} }};
    const vm = require("vm");
    vm.runInThisContext(require("fs").readFileSync({json.dumps(str(BADGES_JS))}, "utf8"));
    const before = {json.dumps(before)}, after = {json.dumps(after)};
    const r = badgeReport(before, after);
    console.log(JSON.stringify({{
      levels: BADGES.map((b) => badgeLevel(after, b)),
      earned: r.earned.map((e) => [e.badge.id, e.level]),
      next: r.next && [r.next.badge.id, r.next.level],
      goal: badgeGoal(BADGES[0], 1) + " / " + badgeGoal(BADGES[0], 10),
    }}));
    """
    out = json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out["levels"] == [badges.level(after, b) for b in defs]
    assert out["earned"] == [[b["id"], badges.level(after, b)] for b in defs if badges.level(after, b)]
    assert out["goal"] == "Play 1 match / Play 10 matches"
    assert out["next"] is not None


def match_entry(k=0, **kw):
    e = {"id": f"m{k}", "at": 1_800_000_000 + k, "mode": "ffa", "map": "classic", "place": 1, "of": 4,
         "won": True, "kos": 1, "falls": 0, "deaths": 0, "pickups": 0, "players": 4, "people": 2, "hour": 15}
    return {**e, **kw}


def feats_of(**kw):
    return profiles.record(profiles.empty("x"), match_entry(**kw))["history"][0]["feats"]


def test_a_match_says_its_own_silly_highlights():
    assert feats_of() == {}
    assert feats_of(people=1) == {"bots_only": 1}
    assert feats_of(people=1, players=1) == {}  # (alone, not with bots)
    assert feats_of(hour=3) == {"night_owl": 1} and feats_of(hour=12) == {"lunch": 1}
    assert feats_of(hour=-1) == {}  # (we don't know your clock)
    assert feats_of(place=2, won=False) == {"second": 1}
    assert feats_of(place=2, of=2, players=2, won=False) == {"last": 1}  # (2nd of 2 is last)
    assert feats_of(place=2, mode="teams", won=False) == {}  # (Teams: no places)
    assert feats_of(place=4, won=False, kos=0, deaths=2, falls=2)["self_destruct"] == 1
    assert "self_destruct" not in feats_of(place=4, won=False, deaths=2, falls=1)  # (someone got you once)
    assert feats_of(kos=0) == {"lucky_win": 1, "pacifist": 1}
    assert feats_of(people=8, players=8) == {"party": 1}
    assert feats_of(pickups=5) == {"sugar_rush": 1}


def test_groundhog_day_is_ten_in_a_row_on_one_map():
    p = profiles.empty("x")
    for k in range(25):
        p = profiles.record(p, match_entry(k, map="swing" if k != 12 else "classic"))
    got = [k for k, h in enumerate(reversed(p["history"])) if h["feats"].get("groundhog")]
    assert got == [9, 22]  # (the 10th in a row; a different map starts again)
    assert p["stats"]["feats"]["groundhog"] == 2


def test_beating_much_better_or_worse_players():
    from bonk_game.server import rating
    f = rating.social_feats([{"id": "a", "rating": 900, "place": 1, "team": None},
                             {"id": "b", "rating": 1250, "place": 2, "team": None},
                             {"id": "c", "rating": 950, "place": 3, "team": None}])
    assert f == {"a": {"giant_slayer": 1}, "b": {"bully": 1}, "c": {}}
    # Teams: only the other side counts (a and b are teammates 400 apart)
    f = rating.social_feats([{"id": "a", "rating": 900, "place": 1, "team": 0},
                             {"id": "b", "rating": 1300, "place": 1, "team": 0},
                             {"id": "c", "rating": 1000, "place": 2, "team": 1}])
    assert f == {"a": {}, "b": {"bully": 1}, "c": {}}


def test_rivals_after_enough_matches_together():
    from bonk_game.server import rating
    from bonk_game.server.accounts import Accounts
    a = Accounts(":memory:")
    ann = a.sign_in("g-ann", name="Ann")[0]["id"]
    bob = a.sign_in("g-bob", name="Bob")[0]["id"]
    game = [{"id": ann, "place": 1, "won": True, "team": None}, {"id": bob, "place": 2, "won": False, "team": None}]
    rivals = [k for k in range(rating.RIVAL_MATCHES + 3) if a.rate(game)[ann]["feats"].get("rival")]
    assert rivals == [rating.RIVAL_MATCHES - 1]  # (once, on the 25th)


def test_your_clock_and_social_highlights_reach_your_history():
    import asyncio

    from bonk_game.server.room import Room

    async def noop(msg):
        pass

    recorded = {}

    class Ratings:
        def rating(self, uid):
            return None

        def rate(self, players):
            return {p["id"]: {"rating": 1000, "change": 0, "feats": {"giant_slayer": 1} if p["id"] == "u1" else {}}
                    for p in players}

    async def go():
        room = Room("ABCD", recorder=lambda acct, e: recorded.setdefault(acct, e))
        room.ratings = Ratings()
        m = await room.join("t1", "Ann", noop, account="u1")
        m.tz = -5 * 60  # (5 hours behind UTC)
        await room.join("t2", "Bob", noop, account="u2")
        room.rated_accounts = ["u1", "u2"]
        room.results = {"match_id": "ABCD-1", "at": 1_800_000_000, "mode": "ffa", "map": "classic",
                        "slots": [{"kind": "human"}, {"kind": "human"}],
                        "summaries": [{"place": 1, "of": 2, "won": True, "kos": 1, "feats": {}},
                                      {"place": 2, "of": 2, "won": False, "kos": 0, "feats": {}}]}
        room._rate(["u1", "u2"])
        room._record(["u1", "u2"])
        assert room.results["summaries"][0]["feats"] == {"giant_slayer": 1}
        assert "feats" not in room.results["ratings"]["0"]
        # 1_800_000_000 is 08:00 UTC: 03:00 on Ann's clock, unknown on Bob's
        assert recorded["u1"]["hour"] == 3 and recorded["u2"]["hour"] == -1
    asyncio.new_event_loop().run_until_complete(go())
