"""The self-play opponent pool and how the training env uses it."""
import random

import pytest

pytest.importorskip("gymnasium")

from bonk_game.envs.training_env import BonkEnv
from bonk_game.envs.utils.opponents import OpponentPool
from bonk_game.ui.bot import Bot


class Fixed:
    """Stand-in for a trained model."""

    def __init__(self, action=0):
        self.action = action
        self.calls = 0

    def predict(self, obs, *args, **kwargs):
        self.calls += 1
        return self.action, None


def test_pool_only_offers_what_exists():
    pool = OpponentPool("platform", load_bad=False)
    assert set(pool.available()) == {"bot"}
    pool.add_snapshot(Fixed())
    assert set(pool.available()) == {"bot", "self"}


def test_pool_keeps_newest_snapshots():
    pool = OpponentPool("platform", max_snapshots=3, load_bad=False)
    models = [Fixed() for _ in range(5)]
    for m in models:
        pool.add_snapshot(m)
    assert pool.snapshots == models[-3:]


def test_pool_samples_by_weight():
    random.seed(0)
    pool = OpponentPool("platform", weights={"bot": 0.5, "self": 0.5}, load_bad=False)
    snap = Fixed()
    pool.add_snapshot(snap)
    env = BonkEnv(map_name="platform", opponents=pool)
    picks = [pool.sample(env) for _ in range(400)]
    bots = sum(isinstance(p, Bot) for p in picks)
    assert sum(p is snap for p in picks) + bots == 400
    assert 150 < bots < 250


def test_pool_with_no_options_returns_none():
    pool = OpponentPool("platform", weights={"self": 1.0}, load_bad=False)
    assert pool.sample(None) is None


@pytest.mark.parametrize("map_name", ["classic", "platform", "slider", "swing"])
def test_env_plays_against_pool(map_name):
    pool = OpponentPool(map_name, weights={"bot": 1.0}, load_bad=False)
    env = BonkEnv(map_name=map_name, opponents=pool)
    obs, _ = env.reset(seed=1)
    assert isinstance(env.opponent, Bot) and env.opponent.index == 1
    for _ in range(300):
        obs, reward, terminated, truncated, _ = env.step(env.action_space.sample())
        assert env.observation_space.contains(obs)
        if terminated:
            env.reset()


def test_env_picks_new_opponent_each_reset():
    pool = OpponentPool("platform", weights={"self": 1.0}, load_bad=False)
    a, b = Fixed(), Fixed()
    pool.snapshots = [a, b]
    env = BonkEnv(map_name="platform", opponents=pool)
    random.seed(3)
    seen = set()
    for _ in range(20):
        env.reset()
        env.step(0)
        seen.add(id(env.opponent))
    assert seen == {id(a), id(b)}
    assert a.calls and b.calls


def test_snapshot_callback_fills_pool(tmp_path):
    pytest.importorskip("stable_baselines3")
    from stable_baselines3 import PPO
    from bonk_game.envs.utils.opponents import snapshot_callback

    pool = OpponentPool("platform", weights={"bot": 0.5, "self": 0.5}, load_bad=False)
    env = BonkEnv(map_name="platform", opponents=pool)
    model = PPO("MlpPolicy", env, n_steps=64, batch_size=32, device="cpu")
    model.learn(256, callback=snapshot_callback(pool, PPO, 100, str(tmp_path)))
    # One at the start, then one every 100 steps
    assert len(pool.snapshots) >= 3
    action, _ = pool.snapshots[-1].predict(env.reset()[0])
    assert env.action_space.contains(int(action))
