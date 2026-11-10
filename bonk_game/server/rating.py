"""Ratings: one Elo rating for every signed-in player, and the leaderboard.

Every match that's played to the end changes the ratings of the signed-in
people who played it from the start (whatever the map or mode). It's Elo
for any number of players: each player against each other one, a win where
you placed above them, a draw where you placed the same (in Teams, your
teammates placed the same as you, so they don't count). The changes from
all those pairs are averaged, so a 6-player match moves you about as much
as a 1v1 does.

Guests and bots don't count: a match needs two signed-in players, and only
they are rated against each other. (Otherwise anyone could farm points off
a second browser tab, or off easy bots.)

The rules here are the server's alone; the browser just shows what it's
sent (the rating, the tier and how many games are still provisional).
"""
import math

START = 1000          # where everyone starts
K = 32                # how far one match moves you once you're placed
K_NEW = 64            # ... and in your first PLACEMENT matches: twice as far, to
                      # move new players toward their level before they're on the board
PLACEMENT = 3         # matches before you're on the leaderboard
SCALE = 400           # Elo: 400 points apart, the better player wins 10 to 1

# (lowest rating, id, title): the badge for a rating
TIERS = (
    (1500, "champion", "Champion"),
    (1350, "diamond", "Diamond"),
    (1200, "platinum", "Platinum"),
    (1050, "gold", "Gold"),
    (900, "silver", "Silver"),
    (-math.inf, "bronze", "Bronze"),
)


def tier(r):
    """The tier id for a rating."""
    return next(t for lo, t, _ in TIERS if r >= lo)


def badge(row):
    """What the browser shows for a rating row ({rating, games, wins, peak}):
    the rating (rounded), its tier, and how many placement matches are left."""
    if row is None:
        row = {"rating": START, "games": 0, "wins": 0, "peak": START}
    r = round(row["rating"])
    return {"rating": r, "tier": tier(r), "games": row["games"], "wins": row["wins"],
            "peak": round(row["peak"]), "placing": max(0, PLACEMENT - row["games"])}


def expected(a, b):
    """The chance a player rated `a` places above one rated `b`."""
    return 1 / (1 + 10 ** ((b - a) / SCALE))


def update(players):
    """New ratings after a match. players: [{"id", "rating", "games",
    "place", "team"}] (team None outside Teams). Returns {id: change}.
    Fewer than two players: no changes."""
    if len(players) < 2:
        return {}
    out = {}
    for p in players:
        total, n = 0.0, 0
        for q in players:
            if q is p or (p["team"] is not None and q["team"] == p["team"]):
                continue
            won = 1.0 if p["place"] < q["place"] else 0.5 if p["place"] == q["place"] else 0.0
            total += won - expected(p["rating"], q["rating"])
            n += 1
        k = K_NEW if p["games"] < PLACEMENT else K
        out[p["id"]] = k * total / n if n else 0.0
    return out
