"""Opponents for training: a pool the training env samples from each episode.

Training against a single fixed opponent teaches an agent to beat that one
opponent and nothing else. The pool mixes:

- the built-in Bot (bonk_game/ui/bot.py) at a random difficulty, which
  needs no training,
- the map's "bad" PPO agent, if it has been trained,
- snapshots of the agent being trained, taken every so often (self-play).

Every env in a DummyVecEnv runs in the same process, so they can share one
pool object, and a training callback can add snapshots to it as it goes.
"""
import os
import random

from bonk_game.envs.utils.maps import DEFAULT_MAP, agent_dir


class OpponentPool:
    """Weighted mix of opponent kinds; sample() picks one for an episode.

    Args:
        weights: relative chance of each kind ("bot", "bad", "self"). Kinds
            that aren't available (no bad agent yet, no snapshots yet) are
            skipped and the rest are re-weighted.
        max_snapshots: how many past self-snapshots to keep (oldest dropped)
    """

    def __init__(self, map_name=DEFAULT_MAP, weights=None, max_snapshots=5, load_bad=True, rng=None):
        """rng: random numbers for picking (a random.Random; None: one seeded
        from Python's global random numbers)."""
        self.rng = random.Random(random.getrandbits(32)) if rng is None else rng
        self.map_name = map_name
        self.weights = dict(weights or {"bot": 0.35, "bad": 0.15, "self": 0.5})
        self.max_snapshots = max_snapshots
        self.snapshots = []
        self.bad = None
        bad_path = f"{agent_dir(map_name)}/bad"
        if load_bad and self.weights.get("bad") and os.path.exists(f"{bad_path}.zip"):
            from stable_baselines3 import PPO
            self.bad = PPO.load(bad_path, device="cpu")

    def available(self):
        kinds = {"bot": True, "bad": self.bad is not None, "self": bool(self.snapshots)}
        return {k: w for k, w in self.weights.items() if w > 0 and kinds.get(k)}

    def add_snapshot(self, model):
        self.snapshots.append(model)
        del self.snapshots[:-self.max_snapshots]

    def sample(self, env, index=1):
        """An opponent (anything with predict(obs)) for player `index` of env."""
        options = self.available()
        if not options:
            return None
        kind = self.rng.choices(list(options), weights=list(options.values()))[0]
        if kind == "bot":
            from bonk_game.ui.bot import LEVEL_NAMES, Bot
            return Bot(env, index, self.rng.choice(LEVEL_NAMES), rng=random.Random(self.rng.getrandbits(32)))
        if kind == "bad":
            return self.bad
        return self.rng.choice(self.snapshots)


def snapshot_callback(pool, model_cls, every, folder):
    """An SB3 callback that adds a frozen copy of the learner to the pool
    every `every` timesteps."""
    from stable_baselines3.common.callbacks import BaseCallback

    class SnapshotCallback(BaseCallback):
        def __init__(self):
            super().__init__()
            self.last = 0
            self.count = 0

        def _on_training_start(self):
            self._snapshot()

        def _on_step(self):
            if self.num_timesteps - self.last >= every:
                self._snapshot()
            return True

        def _snapshot(self):
            self.last = self.num_timesteps
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"snapshot_{self.count % pool.max_snapshots}")
            self.count += 1
            self.model.save(path)
            pool.add_snapshot(model_cls.load(path, device="cpu"))

    return SnapshotCallback()
