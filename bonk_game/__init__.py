from gymnasium.envs.registration import register

from bonk_game.envs.utils.maps import MAPS, env_id

# One gym env per map: bonk_game/bonk-v0 (classic), bonk_game/bonk-swing-v0, ...
for _name in MAPS:
    register(
        id=env_id(_name),
        entry_point="bonk_game.envs:BonkEnv",
        max_episode_steps=15000,
        kwargs={"map_name": _name},
    )
