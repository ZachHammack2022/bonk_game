"""Maps loaded from JSON files (issue #10)."""
import json

import numpy as np
import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.envs.utils import map_files
from bonk_game.envs.utils.map_files import MapFileError, load_all, parse
from bonk_game.envs.utils.maps import MAPS, env_id, make_map

BASIC = {
    "name": "tiny",
    "spawn": [260, 420, 200, 298],
    "pieces": [{"type": "block", "rect": [240, 300, 440, 316]}],
}


def with_(**changes):
    d = json.loads(json.dumps(BASIC))
    d.update(changes)
    return d


def test_shipped_map_files_are_registered():
    assert "ramps" in MAPS
    m = make_map("ramps")
    assert m.title == "Ramp Rumble" and not m.can_fly and m.winning_score == 5
    assert env_id("ramps") == "bonk_game/bonk-ramps-v0"


def test_minimal_map_uses_defaults():
    cls = parse(BASIC)
    m = cls()
    assert cls.title == "Tiny" and cls.reset_round_on_kill and cls.round_time == 45
    assert len(m.blocks) == 1 and m.obs_size == 12 and len(m.extra_obs()) == 0


def test_rules_are_applied():
    cls = parse(with_(rules={"movement": "fly", "first_to": 3, "round_time": 0,
                             "on_death": "respawn", "max_speed": 20}))
    assert cls.can_fly and cls.winning_score == 3 and cls.round_time == 0
    assert not cls.reset_round_on_kill and cls.max_speed == 20


def test_every_piece_type_builds():
    cls = parse(with_(pieces=[
        {"type": "block", "rect": [240, 300, 440, 316], "bounce": 0.2, "friction": 0.1},
        {"type": "slope", "center": [200, 280], "size": [100, 14], "angle": 25},
        {"type": "post", "foot": [250, 300], "size": [10, 40], "lean": -15},
        {"type": "bumper", "center": [340, 200], "radius": 15, "launch": 12},
        {"type": "block", "rect": [0, 470, 680, 480], "kill": True, "color": [10, 20, 30]},
    ]))
    m = cls()
    assert len(m.blocks) == 5
    assert m.blocks[4].kill and m.blocks[4].color == (10, 20, 30)


def test_swing_and_slider_add_observations_and_move():
    cls = parse(with_(pieces=[
        {"type": "swing", "pivot": [340, 30], "length": 200},
        {"type": "slider", "travel": 100, "pieces": [
            {"type": "block", "rect": [240, 300, 440, 316]},
            {"type": "post", "foot": [245, 300], "size": [10, 40], "lean": -18}]},
    ]))
    m = cls()
    assert cls.n_extra_obs == 4 and len(m.extra_obs()) == 4
    m.sliders[0].vx = 5
    m.swings[0].omega = 0.05
    m.step()
    assert m.sliders[0].offset > 0 and m.swings[0].theta > 0
    assert np.all(np.abs(m.extra_obs()) <= 1)
    lo, hi = m.safe_x_range()
    assert lo == 260 + m.sliders[0].offset
    m.reset()
    assert m.sliders[0].offset == 0 and m.swings[0].theta == 0


def test_a_match_on_a_file_map_finishes():
    import random
    from bonk_game.ui.app import Sim
    random.seed(0)
    sim = Sim("ramps", ["bot", "bot"], 2)
    for _ in range(20000):
        sim.step()
        if sim.done:
            break
    assert sim.done


@pytest.mark.parametrize("data, message", [
    ([], "one JSON object"),
    (with_(name="Big Map"), "lowercase"),
    (with_(colour="red"), "unknown key 'colour'"),
    ({k: v for k, v in BASIC.items() if k != "spawn"}, 'missing "spawn"'),
    (with_(spawn=[1, 2, 3]), "spawn: expected a list of 4 numbers"),
    (with_(spawn=[300, 310, 0, 100]), "at least 44 px"),
    (with_(pieces=[]), "at least one piece"),
    (with_(pieces=[{"type": "blok"}]), "pieces[0].type: unknown piece type 'blok'"),
    (with_(pieces=[{"type": "block"}]), 'pieces[0]: missing "rect"'),
    (with_(pieces=[{"type": "block", "rect": [10, 10, 5, 20]}]), "right > left"),
    (with_(pieces=[{"type": "block", "rect": [0, 0, 9, "x"]}]), 'pieces[0].rect[3]: expected a number, got "x"'),
    (with_(pieces=[{"type": "bumper", "center": [1, 2], "radius": 5, "bounce": 7}]), "bounce: must be at most"),
    (with_(pieces=[{"type": "block", "rect": [0, 0, 9, 9], "color": "purple"}]), "unknown colour 'purple'"),
    (with_(pieces=[{"type": "slider", "travel": 50, "pieces": [{"type": "nope"}]}]),
     "pieces[0].pieces[0].type: unknown piece type"),
    (with_(rules={"movement": "swim"}), 'should be "jump" or "fly"'),
    (with_(rules={"first_to": 0}), "at least 1"),
    (with_(rules={"lives": 3}), "unknown key 'lives'"),
])
def test_bad_files_get_clear_errors(data, message):
    with pytest.raises(MapFileError) as e:
        parse(data, "bad.json")
    assert message in str(e.value)
    assert str(e.value).startswith("bad.json")


def test_invalid_json_reports_the_line(tmp_path):
    f = tmp_path / "broken.json"
    f.write_text('{\n  "name": "x",\n  "spawn": [1, 2,]\n}')
    with pytest.raises(MapFileError, match=r"broken.json: not valid JSON \(line 3"):
        map_files.load_file(str(f))


def test_folder_loading_skips_bad_files_and_duplicates(tmp_path, monkeypatch):
    (tmp_path / "good.json").write_text(json.dumps(with_(name="good_one")))
    (tmp_path / "bad.json").write_text("{")
    (tmp_path / "dupe.json").write_text(json.dumps(with_(name="classic")))
    monkeypatch.setenv("BONK_MAPS", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    warnings = []
    found = load_all({"classic": object}, warn=warnings.append)
    assert "good_one" in found and "ramps" in found
    assert "classic" not in found
    assert any("bad.json" in w and "not valid JSON" in w for w in warnings)
    assert any("already a map called 'classic'" in w for w in warnings)


def test_check_map_command(tmp_path, capsys):
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(BASIC))
    bad.write_text(json.dumps(with_(pieces=[{"type": "blok"}])))
    assert map_files.main([str(good)]) == 0
    assert map_files.main([str(good), str(bad)]) == 1
    out = capsys.readouterr().out
    assert "good.json: ok" in out and "unknown piece type 'blok'" in out


def test_file_maps_work_in_the_game_env():
    env = TestEnv("ai", "ai", map_name="ramps")
    obs = env.reset()
    assert len(obs) == 2 * env.obs_size
    for _ in range(100):
        obs, done, _ = env.step([0, 3])
