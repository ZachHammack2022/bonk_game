"""Ratings (rating.py): Elo for every match, kept per account, and the
leaderboard."""
import asyncio

import pytest

from bonk_game.server import rating
from bonk_game.server.accounts import Accounts


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def player(id_, place, r=rating.START, games=10, team=None):
    return {"id": id_, "place": place, "rating": r, "games": games, "team": team}


def test_a_1v1_between_equals_moves_half_k():
    ch = rating.update([player("a", 1), player("b", 2)])
    assert ch["a"] == pytest.approx(rating.K / 2) and ch["b"] == pytest.approx(-rating.K / 2)


def test_beating_someone_better_is_worth_more():
    up = rating.update([player("a", 1, 1000), player("b", 2, 1300)])["a"]
    down = rating.update([player("a", 1, 1300), player("b", 2, 1000)])["a"]
    assert up > rating.K / 2 > down > 0


def test_free_for_all_is_by_place_and_adds_up_to_nothing():
    ch = rating.update([player(k, p) for k, p in zip("abcd", (1, 2, 3, 4))])
    assert ch["a"] > ch["b"] > 0 > ch["c"] > ch["d"]
    assert sum(ch.values()) == pytest.approx(0)
    # (A 4-player win moves you about as much as a 1v1 one)
    assert ch["a"] == pytest.approx(rating.K / 2)


def test_a_shared_place_is_a_draw():
    ch = rating.update([player("a", 1), player("b", 1)])
    assert ch == {"a": 0, "b": 0}


def test_teammates_are_not_rated_against_each_other():
    ch = rating.update([player("a", 1, 1200, team=0), player("b", 1, 900, team=0),
                        player("c", 2, team=1), player("d", 2, team=1)])
    assert ch["a"] > 0 and ch["b"] > 0 and ch["c"] < 0
    assert ch["b"] > ch["a"]  # (the weaker winner was less expected to win)


def test_new_players_move_faster():
    ch = rating.update([player("a", 1, games=0), player("b", 2)])
    assert ch["a"] == pytest.approx(rating.K_NEW / 2) and ch["b"] == pytest.approx(-rating.K / 2)


def test_one_player_is_not_rated():
    assert rating.update([player("a", 1)]) == {}


def test_tiers():
    assert [rating.tier(r) for r in (500, 900, 1000, 1050, 1200, 1350, 1500, 2000)] == \
        ["bronze", "silver", "silver", "gold", "platinum", "diamond", "champion", "champion"]
    assert rating.tier(rating.START) == "silver"


def accounts_with(*names):
    a = Accounts(":memory:")
    ids = []
    for n in names:
        u, _ = a.sign_in("g-" + n, name=n)
        ids.append(u["id"])
    return a, ids


def test_accounts_keep_ratings_and_place_on_the_leaderboard():
    a, (ann, bob, cat) = accounts_with("Ann", "Bob", "Cat")
    assert a.rating(ann) == {"rating": rating.START, "tier": "silver", "games": 0, "wins": 0,
                             "peak": rating.START, "placing": rating.PLACEMENT, "rank": None,
                             "top": False}
    assert a.leaderboard() == ([], 0)
    out = a.rate([{"id": ann, "place": 1, "won": True, "team": None},
                  {"id": bob, "place": 2, "won": False, "team": None}])
    assert out[ann]["before"] == rating.START and out[ann]["change"] == rating.K_NEW // 2
    assert out[ann]["rating"] == rating.START + rating.K_NEW // 2 and out[bob]["change"] < 0
    # Nobody's on the leaderboard until they've played PLACEMENT matches
    for _ in range(rating.PLACEMENT - 1):
        a.rate([{"id": ann, "place": 1, "won": True, "team": None},
                {"id": bob, "place": 2, "won": False, "team": None}])
    rows, total = a.leaderboard()
    assert total == 2 and [r["name"] for r in rows] == ["Ann", "Bob"] and [r["rank"] for r in rows] == [1, 2]
    assert rows[0]["wins"] == rating.PLACEMENT and rows[0]["games"] == rating.PLACEMENT
    assert rows[0]["peak"] == rows[0]["rating"] and rows[1]["peak"] < rating.START  # (Bob only went down)
    assert set(rows[0]["ball"]) == {"color", "own_color", "pattern", "hat"}
    assert a.rating(ann)["rank"] == 1 and a.rating(bob)["rank"] == 2 and a.rating(cat)["rank"] is None
    # Deleting an account takes its rating with it
    a.delete(bob)
    assert a.leaderboard()[1] == 1


def test_one_signed_in_player_is_not_rated():
    a, (ann,) = accounts_with("Ann")
    assert a.rate([{"id": ann, "place": 1, "won": True, "team": None}]) == {}
    assert a.rating(ann)["games"] == 0


def test_rooms_rate_signed_in_people_who_played_from_the_start():
    from bonk_game.server.room import Room

    async def noop(msg):
        pass

    a, (ann, bob) = accounts_with("Ann", "Bob")

    async def go():
        room = Room("ABCD")
        room.ratings = a
        await room.join("t-ann", "Ann", noop, account=ann)
        await room.join("t-bob", "Bob", noop, account=bob)
        await room.join("t-gus", "Gus", noop)  # a guest
        assert room.members["t-ann"].rating["rating"] == rating.START
        assert "rating" not in next(m for m in room.lobby()["members"] if m["name"] == "Gus")
        # Slots: Bob, a guest, Ann, someone who dropped in for a bot (Ann's
        # second account, say), and a bot. Bob won, the guest came 2nd, Ann 3rd
        accounts = [bob, None, ann, "u-dropped-in", None]
        room.rated_accounts = [bob, None, ann, None, None]
        room.results = {"slots": [{}, {}, {}, {}, {}],
                        "summaries": [{"place": p, "won": p == 1} for p in (1, 2, 3, 4, 5)]}
        room._rate(accounts)
        r = room.results["ratings"]
        assert set(r) == {"0", "2"}  # (only Bob and Ann: the guest and the drop-in don't count)
        assert r["0"]["change"] == rating.K_NEW // 2 and r["2"]["change"] == -(rating.K_NEW // 2)
        assert room.members["t-bob"].rating["rating"] == rating.START + rating.K_NEW // 2
        assert next(m for m in room.lobby()["members"] if m["name"] == "Bob")["rating"]["games"] == 1
    run(go())


def test_the_leaderboard_api():
    pytest.importorskip("aiohttp")
    from aiohttp.test_utils import TestClient, TestServer

    from bonk_game.server import auth
    from bonk_game.server.web import make_app
    a, (ann, bob) = accounts_with("Ann", "Bob")
    for _ in range(rating.PLACEMENT):
        a.rate([{"id": ann, "place": 1, "won": True, "team": None},
                {"id": bob, "place": 2, "won": False, "team": None}])

    async def go():
        cfg = auth.Config(client_id="c", client_secret="s", db=":memory:", public_url="")
        app = make_app(auth_config=cfg, accounts=a)
        async with TestClient(TestServer(app)) as client:
            d = await (await client.get("/api/leaderboard")).json()
            assert d["total"] == 2 and d["you"] is None and d["placement"] == rating.PLACEMENT
            assert [p["name"] for p in d["players"]] == ["Ann", "Bob"]
            assert not any("account" in p or p["you"] for p in d["players"])  # (no account ids)
            assert (await client.get("/leaderboard")).status == 200
    run(go())


def test_the_best_player_wears_a_crown_once_theyre_gold():
    assert rating.crowned(1, rating.CROWN_MIN) and not rating.crowned(1, rating.CROWN_MIN - 1)
    assert not rating.crowned(2, 2000) and not rating.crowned(None, 2000)
    a, (ann, bob) = accounts_with("Ann", "Bob")
    ann_won = [{"id": ann, "place": 1, "won": True, "team": None},
               {"id": bob, "place": 2, "won": False, "team": None}]
    draw = [{**p, "place": 1, "won": False} for p in ann_won]
    for _ in range(rating.PLACEMENT):
        out = a.rate(draw)
    # Both #1 on the board (level), but not good enough for the crown (still
    # at the start, in Silver)
    assert a.rating(ann)["rank"] == 1 and a.rating(ann)["rating"] < rating.CROWN_MIN
    assert not out[ann]["top"] and not a.leaderboard()[0][0]["top"]
    while a.rating(ann)["rating"] < rating.CROWN_MIN:
        out = a.rate(ann_won)
    assert out[ann]["top"] and not out[bob]["top"]
    assert a.rating(ann)["top"] and not a.rating(bob)["top"]
    rows, _ = a.leaderboard()
    assert [r["top"] for r in rows] == [True, False]
