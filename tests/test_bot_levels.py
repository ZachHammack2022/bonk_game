"""Bot difficulty levels (issue #11)."""
import random

import numpy as np
import pytest

from bonk_game.envs.testing_env import TestEnv
from bonk_game.ui.bot import LEVEL_NAMES, LEVELS, Bot


def match(map_name, a, b, seed, first_to=5):
    random.seed(seed)
    np.random.seed(seed)
    env = TestEnv("ai", "ai", map_name=map_name, winning_score=first_to)
    bots = [Bot(env, 0, a), Bot(env, 1, b)]
    env.reset()
    for _ in range(30000):
        _, done, _ = env.step([bots[0].predict(None)[0], bots[1].predict(None)[0]])
        if done:
            break
    return env.scores


def wins(map_name, strong, weak, n):
    """Matches `strong` wins out of n, swapping sides every other match."""
    won = 0
    for seed in range(n):
        if seed % 2:
            s = match(map_name, weak, strong, seed)
            won += s[1] > s[0]
        else:
            s = match(map_name, strong, weak, seed)
            won += s[0] > s[1]
    return won


@pytest.mark.parametrize("strong, weak", [("medium", "easy"), ("hard", "medium")])
def test_each_level_beats_the_one_below(strong, weak):
    # Fixed seeds, so this is deterministic. Wider runs (24 matches on each
    # of 5 maps) gave 77% for medium over easy and 68% for hard over medium.
    won = sum(wins(m, strong, weak, 16) for m in ("platform", "ramps", "classic"))
    assert won >= 30  # of 48 (currently 39 and 38)


def test_levels_are_the_three_names():
    assert LEVEL_NAMES == ("easy", "medium", "hard")
    assert set(LEVELS["easy"]) == set(LEVELS["hard"])


def test_unknown_level_is_rejected():
    env = TestEnv("ai", "ai", map_name="platform")
    with pytest.raises(ValueError, match="Unknown bot level"):
        Bot(env, 0, "impossible")


def test_ui_bot_choices():
    from bonk_game.ui.app import BOT_CHOICES, Sim, describe
    assert BOT_CHOICES == ("bot:easy", "bot:medium", "bot:hard")
    assert describe("bot:hard") == "Hard bot" and describe("bot") == "Medium bot"
    sim = Sim("platform", ["bot:easy", "bot:hard"], 5)
    assert [c.level for c in sim.controllers] == ["easy", "hard"]
    assert Sim("platform", ["bot", "human"], 5).controllers[0].level == "medium"


def test_training_pool_mixes_levels():
    pytest.importorskip("gymnasium")
    from bonk_game.envs.training_env import BonkEnv
    from bonk_game.envs.utils.opponents import OpponentPool
    random.seed(0)
    pool = OpponentPool("platform", weights={"bot": 1.0}, load_bad=False)
    env = BonkEnv(map_name="platform", opponents=pool)
    assert {pool.sample(env).level for _ in range(60)} == set(LEVEL_NAMES)
