from bonk_game.envs.testing_env import TestEnv


class MatchEnv():
    """Runs a headless match between two trained agents."""

    def __init__(self, agent1, agent2, render_mode=None, map_name="classic"):
        # user participation in tournament currently not supported
        assert agent1 is not None and agent2 is not None
        assert agent1 != "user" and agent2 != "user"

        self.env = TestEnv(agent1, agent2, render_mode, map_name=map_name)
        self.agent1 = agent1
        self.agent2 = agent2

    def simulate(self, steps):
        """Play up to `steps` steps and return [agent1 score, agent2 score]."""
        obs = self.env.reset()
        n = self.env.obs_size
        for _ in range(steps):
            action1, _states = self.agent1.predict(obs[:n])
            action2, _states = self.agent2.predict(obs[n:])
            obs, done, info = self.env.step([action1, action2])
            if done:
                break
        self.env.close()
        return self.env.scores
