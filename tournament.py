import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import random

from bonk_game.envs.match_env import MatchEnv
from bonk_game.envs.utils.testing import load_agents, model_classes


def play_match(key1, a1, key2, a2, steps):
    """Return the winning key. Ties are settled by a coin flip."""
    s1, s2 = MatchEnv(a1, a2).simulate(steps)
    print(f"{key1} vs {key2}: {s1}:{s2}")
    if s1 == s2:
        return random.choice([key1, key2])
    return key1 if s1 > s2 else key2


def run_tournament(participants, steps=5000):
    """Single-elimination bracket. Returns the name of the winner.

    With an odd number of players, one random player gets a bye into the
    next round instead of being knocked out without playing.
    """
    remaining = list(participants)
    round_num = 1
    while len(remaining) > 1:
        print(f"--- Round {round_num} ---")
        random.shuffle(remaining)
        next_round = []
        if len(remaining) % 2 == 1:
            bye = remaining.pop()
            print(f"{bye} gets a bye")
            next_round.append(bye)
        for key1, key2 in zip(remaining[::2], remaining[1::2]):
            next_round.append(play_match(key1, participants[key1],
                                         key2, participants[key2], steps))
        remaining = next_round
        round_num += 1
    return remaining[0]


if __name__ == "__main__":
    agents = load_agents(model_classes())
    if len(agents) < 2:
        raise SystemExit("Need at least two trained agents. Run `python3 main.py` first.")

    winner = run_tournament(agents, steps=100000)
    print(f"The winner of the tournament is the {winner} agent!")
