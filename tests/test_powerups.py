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


# --- swap and ghost --------------------------------------------------------------
def test_swap_trades_places_with_an_opponent():
    env, ups = setup(2, "platform")
    a, b = env.players
    a.x, a.y, a.x_v, b.x, b.y, b.x_v = 250.0, 270.0, 3.0, 430.0, 270.0, -2.0
    ups.pickups = [[a.x, a.y, "swap"]]
    events = ups.step(NOTHING)
    swap = next(e for e in events if e["e"] == "swap")
    assert swap["i"] == 0 and swap["j"] == 1
    assert (a.x, a.x_v, b.x, b.x_v) == (430.0, -2.0, 250.0, 3.0)
    assert ups.effects == [None, None] and env.last_hit[1][0] == 0  # (instant; their fall is on you)


def test_a_ghost_goes_through_other_balls_but_not_the_level():
    env, ups = setup(2, "platform")
    a, b = env.players
    for p, x in ((a, 300.0), (b, 360.0)):
        p.x, p.y, p.x_v, p.y_v = x, 279.0, 0.0, 0.0
    ups.effects[0] = ["ghost", 150]
    for _ in range(40):
        ups.apply()
        env.step([Buttons(right=True), None])
    assert a.x > b.x + 10  # straight through
    assert abs(b.x - 360) < 1 and abs(b.x_v) < 0.1  # (b wasn't touched)
    assert a.alive and abs(a.y - 279) < 2  # still standing on the platform
    ups.effects[0] = None
    ups.apply()
    assert not a.ghost


# --- giant -----------------------------------------------------------------------
def bump_speed(giant):
    """How fast a ball running into a resting one sends it."""
    env, ups = setup(2, "platform")
    a, b = env.players
    a.x, a.y = 250.0, 279.0 - (a.base_r * (pu.GIANT_SIZE - 1) if giant else 0)
    b.x, b.y = 380.0, 279.0
    if giant:
        ups.effects[0] = ["giant", 300]
    fastest = 0
    for _ in range(60):
        ups.apply()
        env.step([Buttons(right=True), None])
        fastest = max(fastest, b.x_v)
    return fastest


def test_a_giant_is_bigger_and_hits_harder():
    env, ups = setup(2, "platform")
    ups.effects[0] = ["giant", 3]
    ups.apply()
    p = env.players[0]
    assert p.r == p.base_r * pu.GIANT_SIZE and ups.state()["sizes"][0] == p.r
    env.step()
    assert env.map.world.ball(p).body.fixtures[0].shape.radius * 40 == pytest.approx(p.r)
    assert bump_speed(True) > bump_speed(False) * 1.3
    for _ in range(4):
        ups.step(NOTHING)
        ups.apply()
    assert p.r == p.base_r and "sizes" not in ups.state()


# --- black hole --------------------------------------------------------------------
def test_a_black_hole_pulls_everyone_else_in_and_knocks_them_out():
    m = plane_match(n=3, others="human")
    m.powerups.pending = (0, "hole")  # (a black hole instead)
    fly_hole = m.powerups
    for _ in range(int(pu.INTRO_SECONDS * 30) + 1):
        if m.phase == "play":
            break
        m.tick()
    assert fly_hole.hole is not None and m.snapshot()["hole"]["safe"] == [0]
    h = fly_hole.hole
    owner, victim = m.env.players[0], m.env.players[1]
    victim.x, victim.y = h["x"] + 10, h["y"] + 60
    owner.x = h["x"] - 120
    events = []
    for _ in range(pu.HOLE_SECONDS * 30):
        events += m.tick()
        if m.phase != "play" or fly_hole.hole is None:
            break
    deaths = [e for e in events if e["e"] == "death"]
    assert deaths and all(d["i"] != 0 and d["by"] == 0 for d in deaths)
    assert any(d["i"] == 1 for d in deaths)


def test_the_black_hole_closes_after_a_while():
    env, ups = setup(3, "platform")
    ups.pending = (0, "hole")
    ups.launch()
    for p in env.players[1:]:
        p.held = 10 ** 6  # (out of reach, so nobody gets eaten)
    events = []
    for _ in range(pu.HOLE_SECONDS * 30):
        ups.apply()
        env.step()
        events += ups.step(NOTHING)
    assert ups.hole is None and [e["e"] for e in events].count("hole_end") == 1


# --- swarm -----------------------------------------------------------------------------
def swarm():
    env, ups = setup(3, "platform")
    me = env.players[0]
    me.x, me.y = 340.0, 279.0
    for p, x in zip(env.players[1:], (210.0, 470.0)):
        p.x, p.y, p.held = x, 279.0, 10 ** 6  # (out of the way)
    ups.pending = (0, "swarm")
    ups.launch()
    return env, ups, me


def test_a_swarm_copies_your_moves():
    env, ups, me = swarm()
    assert len(env.copies) == pu.SWARM_COPIES and ups.effects[0][0] == "swarm"
    assert len(ups.state()["copies"]) == pu.SWARM_COPIES
    start = [c.x for _, c in env.copies] + [me.x]
    for _ in range(20):
        ups.apply()
        env.step([Buttons(right=True), None, None])
        ups.step(NOTHING)
    moved = [c.x for _, c in env.copies] + [me.x]
    assert all(b - a > 10 for a, b in zip(start, moved))
    # They never bump into you or each other
    assert me.group < 0 and all(c.group == me.group for _, c in env.copies)


def test_copies_can_fall_off_without_costing_you_anything():
    env, ups, me = swarm()
    _, gone = env.copies[0]
    gone.x, gone.y = 600.0, 470.0  # (about to fall out)
    events = []
    for _ in range(20):
        ups.apply()
        env.step()
        events += ups.step(NOTHING)
    assert any(e["e"] == "pop" and not e["end"] for e in events)
    assert len(env.copies) == pu.SWARM_COPIES - 1 and me.alive


def test_a_copy_bumping_someone_counts_as_you():
    env, ups, me = swarm()
    other = env.players[1]
    other.held = 0
    _, c = max(env.copies, key=lambda oc: oc[1].x)  # (the one on the right, away from you)
    other.x, other.y, other.x_v = c.x + 60, c.y, 0.0
    c.x_v = 12.0
    for _ in range(8):
        ups.apply()
        env.step()
        ups.step(NOTHING)
    assert env.last_hit[1] is not None and env.last_hit[1][0] == 0
    assert env.last_hit[0] is None  # (nobody touched the real you)


def test_the_swarm_goes_when_it_runs_out_or_you_are_knocked_out():
    env, ups, me = swarm()
    ups.step({**NOTHING, "kos": [(0, None, False)]})
    assert env.copies == []
    env, ups, me = swarm()
    ups.effects[0][1] = 1
    events = ups.step(NOTHING)
    assert env.copies == [] and sum(e["e"] == "pop" and e["end"] for e in events) == pu.SWARM_COPIES


def test_one_super_at_a_time_whatever_it_is():
    env, ups, me = swarm()
    ups.kinds = list(pu.SUPERS)
    assert ups.busy() and ups._pick_kind() is None
    ups.pickups = [[me.x, me.y, "giant"]]
    assert not [e for e in ups.step(NOTHING) if e["e"] == "pickup"]  # (left where it is)


@pytest.mark.parametrize("kind", ["hole", "giant", "swarm", "ghost", "swap"])
def test_a_match_with_just_one_kind(kind):
    m = Match("platform", [{"kind": "bot:hard", "name": f"b{i}"} for i in range(4)], 3,
              power_ups=True, power_kinds=[kind], seed=5)
    seen = set()
    for _ in range(30 * 240):
        for e in m.tick():
            seen.add(e.get("k") if e["e"] == "pickup" else e["e"])
        json.dumps(m.snapshot())
        if m.finished:
            break
    assert kind in seen
