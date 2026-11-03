"""The lobby's rules (bonk_game/server/lobby.py), without a Room."""
from types import SimpleNamespace

from bonk_game.envs.utils.maps import MAPS
from bonk_game.server import lobby, modes

BOTS = lambda settings: ["bot:easy", "bot:medium", "bot:hard"]


def test_a_bad_change_keeps_the_settings_as_they_were():
    s = lobby.default_settings()
    for msg, problem in [({"map": "nope"}, "Unknown map."), ({"mode": "nope"}, "Unknown mode."),
                         ({"first_to": "lots"}, "First to should be a number."),
                         ({"round_time": 17}, "Unknown round time."), ({"gravity": "huge"}, "Unknown gravity."),
                         ({"power_ups": "yes"}, "Power-ups should be on or off.")]:
        out, said = lobby.check_settings(s, {"map": "classic", **msg} if "map" not in msg else msg, 1, BOTS)
        assert said == problem and out == s


def test_changes_are_applied_and_the_goal_follows_the_mode():
    s, problem = lobby.check_settings(lobby.default_settings(), {"mode": "lives", "first_to": 500}, 1, BOTS)
    assert problem is None and s["mode"] == "lives" and s["first_to"] == lobby.FIRST_TO_RANGE[1]
    s, _ = lobby.check_settings(s, {"mode": "crown"}, 1, BOTS)
    assert s["first_to"] == modes.MODES["crown"].goal_default


def test_a_respawn_mode_moves_to_a_map_that_can_respawn():
    s = {**lobby.default_settings(), "map": next(n for n in MAPS if not MAPS[n].respawn_ok)}
    s, problem = lobby.check_settings(s, {"mode": "knockouts"}, 1, BOTS)
    assert problem is None and MAPS[s["map"]].respawn_ok


def test_too_many_people_for_a_map():
    small = min(MAPS, key=lambda n: MAPS[n].players[1])
    most = MAPS[small].players[1]
    _, problem = lobby.check_settings(lobby.default_settings(), {"map": small}, most + 1, BOTS)
    assert problem and str(most) in problem


def test_unknown_bots_are_refused_and_agents_for_another_map_replaced():
    s, problem = lobby.check_settings(lobby.default_settings(), {"bots": ["bot:hard", "skynet"]}, 1, BOTS)
    assert problem == "Unknown bot." and s["bots"] == ["bot:medium"]
    # An agent that can't play the new map becomes a Medium bot
    s = {**lobby.default_settings(), "bots": ["ppo", "bot:easy"]}
    s, problem = lobby.check_settings(s, {"map": "classic"}, 1, BOTS)
    assert problem is None and s["bots"] == ["bot:medium", "bot:easy"]


def test_seats_fill_with_people_first_then_bots():
    s = {**lobby.default_settings(), "map": "platform", "bots": ["bot:easy"] * 9}
    most = MAPS["platform"].players[1]
    humans, bots = lobby.seats(s, [f"p{i}" for i in range(3)])
    assert humans == ["p0", "p1", "p2"] and len(bots) == min(9, most - 3)
    humans, bots = lobby.seats(s, [f"p{i}" for i in range(most + 2)])
    assert len(humans) == most and bots == []


def test_teams_even_out_and_respect_picks():
    assert lobby.teams_for("ffa", [None, None], 2) is None
    teams = lobby.teams_for("teams", [1, 1, None], 3)
    assert teams[:2] == [1, 1] and teams.count(0) == teams.count(1) == 3
    # A side that's full: the rest go to the other one
    picks = [0] * (modes.TEAM_SIZE + 1)
    assert lobby.teams_for("teams", picks, 0).count(0) == modes.TEAM_SIZE


def test_colours_first_come_first_served_and_team_palettes():
    assert lobby.colors_for([3, 3, None], 1) == [3, 0, 1, 2]
    teams = [0, 1, 0, 1]
    colors = lobby.colors_for([None, None], 2, teams)
    assert all(c in modes.TEAM_COLORS[t] for c, t in zip(colors, teams)) and len(set(colors)) == 4


def test_the_lineup_shows_people_then_bots():
    members = {t: SimpleNamespace(name=t.upper(), team=None, color=None, pattern="dots") for t in ("a", "b")}
    seats = lobby.lineup({**lobby.default_settings(), "bots": ["bot:hard"]}, members, ["a", "b"])
    assert [s["kind"] for s in seats] == ["human", "human", "bot:hard"]
    assert seats[0]["name"] == "A" and seats[0]["pattern"] == "dots" and seats[2]["bot"] == 0


def test_names_are_tidied():
    assert lobby.clean_name("  a   b ") == "a b" and lobby.clean_name("") == "Player"
    assert len(lobby.clean_name("x" * 50)) == lobby.NAME_LEN
    assert lobby.bot_label("bot:hard") == "Hard bot" and lobby.bot_label("ppo") == "PPO"
