"""Power-ups (web version, a room setting)."""
import json
import random

import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils.controls import Buttons
from bonk_game.server import powerups as pu
from bonk_game.server.match import Match

NOTHING = {"kos": [], "points": [], "round_over": False, "deaths": []}


def setup(n=2, map_name="classic"):
    env = TestEnv(*[None] * n, map_name=map_name)
    env.reset()
    return env, pu.PowerUps(env, random.Random(0))


def give(env, ups, i, kind):
    """Put a pickup on player i and let them grab it."""
    p = env.players[i]
    ups.pickups = [[p.x, p.y, kind]]
    events = ups.step(NOTHING)
    assert events[0]["e"] == "pickup" and events[0]["i"] == i
    ups.apply()


def test_pickups_appear_in_the_spawn_area():
    env, ups = setup()
    events = []
    for _ in range(int(pu.FIRST_SPAWN * 30) + 1):
        events += ups.step(NOTHING)
    spawns = [e for e in events if e["e"] == "spawn"]
    assert len(spawns) == 1
    left, right, top, bottom = env.map.spawn_box
    x, y, kind = ups.pickups[0]
    assert left <= x <= right and top <= y <= bottom and kind in pu.KINDS
    json.dumps(ups.state())


def test_never_more_than_a_few_at_once():
    env, ups = setup()
    for p in env.players:
        p.alive = 0  # nobody picks anything up
    for _ in range(30 * 60):
        ups.step(NOTHING)
    assert len(ups.pickups) == pu.MAX_ON_MAP


def in_the_air(env):
    """Both balls well apart, high above the level."""
    for k, p in enumerate(env.players):
        p.x, p.y, p.x_v, p.y_v = 200 + 200 * k, 60, 0, 0


def test_speed_pushes_harder():
    env, ups = setup()
    give(env, ups, 0, "speed")
    a, b = env.players
    a.x_v = b.x_v = 0
    a.move_right(2)
    b.move_right(2)
    assert a.x_v == pytest.approx(b.x_v * pu.KINDS["speed"]["force"])
    in_the_air(env)
    a.x_v = b.x_v = 100
    env.map.world.step([a, b])
    assert a.x_v > b.x_v  # higher top speed


def test_float_and_iron():
    env, ups = setup()
    give(env, ups, 0, "float")
    a, b = env.players
    in_the_air(env)
    a.y_v = b.y_v = 0
    env.map.world.step([a, b])
    assert 0 < a.y_v < b.y_v
    give(env, ups, 1, "iron")
    p = env.players[1]
    assert p.m == p.max_m
    p.x_v = 0
    p.move_right(2)
    assert p.x_v == pytest.approx(2 * p.time_scale / p.min_m)  # heavy, but moves like a light ball
    p.end_step()
    assert p.m == p.max_m  # (heavy all along, not only while a button's held)


def test_punch_sends_the_next_player_flying_once():
    env, ups = setup()
    give(env, ups, 0, "punch")
    a, b = env.players
    b.x, b.y = a.x + 30, a.y
    env.steps += 1
    env.last_hit[0] = (1, env.steps)
    events = ups.step(NOTHING)
    assert [e["e"] for e in events] == ["punch"]
    assert b.x_v == pytest.approx(pu.PUNCH_SPEED)
    assert ups.effects[0] is None


def test_effects_run_out_and_end_on_a_knockout():
    env, ups = setup()
    give(env, ups, 0, "speed")
    for _ in range(pu.KINDS["speed"]["seconds"] * 30):
        ups.step(NOTHING)
    assert ups.effects[0] is None
    give(env, ups, 1, "float")
    ups.step({**NOTHING, "kos": [(1, None, False)]})
    assert ups.effects[1] is None
    ups.apply()
    assert env.players[1].gravity_mult == 1.0


def test_a_new_round_clears_everything():
    env, ups = setup(map_name="platform")
    give(env, ups, 0, "iron")
    ups.pickups = [[100, 100, "speed"]]
    ups.step({**NOTHING, "round_over": True})
    assert ups.pickups == [] and ups.effects == [None, None]


@pytest.mark.parametrize("mode", ["ffa", "knockouts"])
def test_a_match_with_power_ups(mode):
    m = Match("platform", [{"kind": "bot:medium", "name": f"b{i}"} for i in range(4)],
              2 if mode == "ffa" else 1, mode=mode, power_ups=True, seed=1)  # (the bots' choices too)
    seen = set()
    for _ in range(200_000):
        seen |= {e["e"] for e in m.tick()}
        if m.finished:
            break
    assert m.finished and "spawn" in seen
    res = m.results()
    json.dumps(res)
    json.dumps(m.snapshot())
    assert m.describe()["powerups"]["speed"]["force"] > 1


def test_off_by_default():
    m = Match("platform", [{"kind": "bot:medium", "name": "a"}, {"kind": "bot:medium", "name": "b"}], 2)
    assert m.powerups is None and "pickups" not in m.snapshot()
    assert m.describe()["powerups"] is None
    # Humans' buttons still work as before
    m.set_input(0, Buttons(right=True))


def test_punch_spares_teammates():
    env = TestEnv(None, None, None, map_name="classic", teams=[0, 0, 1])
    env.reset()
    ups = pu.PowerUps(env, random.Random(0))
    give(env, ups, 0, "punch")
    env.steps += 1
    env.last_hit[0] = (1, env.steps)
    assert ups.step(NOTHING) == [] and ups.effects[0][0] == "punch"


def test_power_ups_dont_change_the_physics_sent_to_browsers():
    m = Match("platform", [{"kind": "bot:medium", "name": f"b{i}"} for i in range(2)], 2, power_ups=True)
    before = m.physics()
    give(m.env, m.powerups, 0, "float")
    give(m.env, m.powerups, 0, "speed")
    assert m.physics() == before


# --- which power-ups a room has ---------------------------------------------
def test_only_the_rooms_kinds_turn_up():
    env = TestEnv(None, None, map_name="classic")
    env.reset()
    ups = pu.PowerUps(env, random.Random(0), kinds=["float", "punch"])
    kinds = set()
    for _ in range(3000):
        for e in ups.step(NOTHING):
            if e["e"] == "spawn":
                kinds.add(e["k"])
        ups.pickups = []  # (make room for the next)
    assert kinds == {"float", "punch"}


def test_a_room_picks_its_power_ups():
    from bonk_game.server import lobby
    bots = lambda s: ["bot:medium"]
    s = lobby.default_settings()
    assert s["power_kinds"] == pu.ALL_KINDS
    out, problem = lobby.check_settings(s, {"power_kinds": ["plane", "speed"]}, 1, bots)
    assert problem is None and out["power_kinds"] == ["speed", "plane"]  # (in the usual order)
    for bad, said in [(["nope"], "Unknown power-up."), ("speed", "Unknown power-up."),
                      ([1], "Unknown power-up."), ([], "Pick at least one power-up.")]:
        assert lobby.check_settings(s, {"power_kinds": bad}, 1, bots) == (s, said)
    m = Match("platform", [{"kind": "bot:medium", "name": f"b{i}"} for i in range(2)], 2,
              power_ups=True, power_kinds=["iron"])
    assert m.powerups.kinds == ["iron"] and m.options["power_kinds"] == ["iron"]


# --- the attack plane (the super power-up) ------------------------------------
def plane_match(map_name="platform", n=3, mode="ffa", others="bot:medium"):
    """A match (you in slot 0, bots in the rest, or people who stand
    still), playing, with an attack plane just picked up by you: the
    cutscene's on."""
    m = Match(map_name, [{"kind": "human", "name": "me"}] + [{"kind": others, "name": f"b{i}"} for i in range(n - 1)],
              5, mode=mode, power_ups=True, power_kinds=["plane"], seed=2)
    while m.phase != "play":
        m.tick()
    p = m.env.players[0]
    m.powerups.pickups = [[p.x, p.y, "plane"]]
    events = m.tick()
    assert [e["e"] for e in events if e["e"] in ("pickup", "super")] == ["pickup", "super"]
    assert m.phase == "super" and m.snapshot()["super"] == [0, "plane"]
    return m


def fly(m):
    """Through the rest of the cutscene, into the air."""
    for _ in range(int(pu.INTRO_SECONDS * 30) + 1):
        if m.phase == "play":
            break
        m.tick()
    assert m.phase == "play" and m.powerups.plane is not None


def test_the_match_stands_still_for_the_cutscene():
    m = plane_match()
    before = m.snapshot()
    for _ in range(int(pu.INTRO_SECONDS * 30) - 2):
        m.tick()
        assert m.phase == "super"
    after = m.snapshot()
    assert after["players"] == before["players"] and after["t"] == before["t"]
    fly(m)
    st = m.snapshot()
    pilot, x, y, facing, left, bombs = st["plane"]
    assert pilot == 0 and bombs == pu.BOMBS and left == pu.PLANE_SECONDS and y == pu.PLANE_Y
    assert st["held"][0] > 0  # out of play while flying


def test_the_pilot_steers_and_cant_be_hit():
    m = plane_match()
    fly(m)
    x0 = m.powerups.plane["x"]
    m.set_input(0, Buttons(right=True))
    for _ in range(10):
        m.tick()
    assert m.powerups.plane["x"] > x0 + 30 and m.powerups.plane["dir"] == 1
    # Holding a key doesn't fly the ball (it's parked, out of play)
    p = m.env.players[0]
    assert p.held and p.alive and (p.x_v, p.y_v) == (0, 0)
    assert m.env.nearest_opponent(1) != 0  # (bots go after someone else)


def bomb_on(m, j):
    """Fly over player j and drop a bomb on them. Returns every event until it goes off."""
    events = []
    for _ in range(200):
        dx = m.env.players[j].x - m.powerups.plane["x"]
        m.set_input(0, Buttons(left=dx < -3, right=dx > 3))
        events += m.tick()
        if abs(dx) <= 3:
            break
    m.set_input(0, Buttons(up=True))
    m.set_input(0, Buttons())  # (a quick tap, let go before the next step, still counts)
    for _ in range(120):
        events += m.tick()
        if any(e["e"] == "boom" for e in events):
            break
    events += m.tick()  # (the blast knocks them out at the start of the next step)
    return events


def test_a_bomb_knocks_out_the_balls_it_lands_near_and_the_pilot_gets_them():
    m = plane_match(n=2, others="human")
    fly(m)
    events = bomb_on(m, 1)
    assert sum(e["e"] == "bomb" for e in events) == 1
    boom = next(e for e in events if e["e"] == "boom")
    assert boom["i"] == 0 and boom["hit"] == [1]
    death = next(e for e in events if e["e"] == "death")
    assert death["i"] == 1 and death["by"] == 0
    # The last one standing was up in the plane: the pilot takes the round
    assert next(e for e in events if e["e"] == "score")["i"] == 0
    assert m.stats[0]["kos"] == 1
    assert m.powerups.plane is None and "plane" not in m.snapshot()


def test_on_a_respawn_map_the_plane_flies_on_and_lands_where_it_took_off():
    m = plane_match("classic", n=3, mode="knockouts", others="human")
    took_off = (m.env.players[0].x, m.env.players[0].y)
    fly(m)
    assert m.powerups.plane_y > m.env.players[0].top  # (inside Classic's box)
    events = bomb_on(m, 1)
    assert any(e["e"] == "death" and e["i"] == 1 and e["by"] == 0 for e in events)
    assert m.powerups.plane is not None and m.powerups.plane["bombs"] == pu.BOMBS - 1
    for _ in range(pu.PLANE_SECONDS * 30):
        events = m.tick()
        if m.powerups.plane is None:
            break
    land = next(e for e in events if e["e"] == "land")
    p = m.env.players[0]
    assert land["i"] == 0 and (p.x, p.y) == took_off and p.held  # (a moment to see where you are)


def test_two_bombs_then_its_over():
    m = plane_match(n=4)
    fly(m)
    dropped = []
    for _ in range(4):
        m.set_input(0, Buttons(down=True))
        dropped += [e for e in m.tick() if e["e"] == "bomb"]
        m.set_input(0, Buttons())
        for _ in range(int(pu.BOMB_GAP * 30) + 1):
            dropped += [e for e in m.tick() if e["e"] == "bomb"]
    assert len(dropped) == pu.BOMBS
    # Once the last one's gone off, the plane doesn't hang about for the full time
    ticks = 0
    while m.powerups.plane is not None and ticks < pu.PLANE_SECONDS * 30:
        m.tick()
        ticks += 1
    assert m.powerups.plane is None and ticks < (pu.PLANE_SECONDS - 3) * 30


def test_a_bot_flies_the_plane_too():
    m = Match("platform", [{"kind": "bot:hard", "name": f"b{i}"} for i in range(3)], 5,
              power_ups=True, power_kinds=["plane"], seed=4)
    while m.phase != "play":
        m.tick()
    p = m.env.players[0]
    m.powerups.pickups = [[p.x, p.y, "plane"]]
    events = []
    for _ in range(int((pu.INTRO_SECONDS + pu.PLANE_SECONDS) * 30) + 5):
        events += m.tick()
    assert sum(e["e"] == "bomb" for e in events) >= 1
    assert any(e["e"] == "boom" for e in events)


def test_one_plane_at_a_time():
    m = plane_match()
    assert not any(k == "plane" for _, _, k in m.powerups.pickups)
    assert m.powerups._pick_kind() is None  # (nothing else is on: nothing spawns)
    m.powerups.kinds = ["plane", "speed"]
    assert all(m.powerups._pick_kind() == "speed" for _ in range(20))


def test_the_plane_is_cleared_between_rounds():
    m = plane_match()
    fly(m)
    m.powerups.step({**NOTHING, "round_over": True})
    assert m.powerups.plane is None and m.powerups.bombs == [] and m.powerups.pending is None
