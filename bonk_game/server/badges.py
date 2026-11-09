"""Badges: goals to work towards, each with levels that get harder.

Every badge counts something in your profile's lifetime stats (profiles.py:
matches, wins, knockouts, ...; and "feats", the highlights each match's
results carry: match.py's new_feats). A badge's level is how many of its
thresholds you've reached. Nothing extra is stored: your badges always
follow from your stats, so guests (whose stats are in their browser) and
signed-in players get them the same way.

The page gets these definitions (web.py puts them in index.html) and
js/badges.js works out your levels, shows them on your Stats tab, and
shows the ones a match earned you on the results screen.
"""
from bonk_game.envs.utils.maps import MAPS
from bonk_game.server import modes

# Level names, easiest first (the same colours as the rating tiers)
LEVELS = ("bronze", "silver", "gold", "platinum", "diamond")

# id, icon, title, what it counts, its thresholds, and what reaching a
# level takes ({n}: the threshold; [a|b]: a for 1, b otherwise).
# "count" is a lifetime stat (profiles.py), "feats.x" a highlight's total,
# "maps" / "modes" how many different ones you've played, "awards" every
# end-of-match award you've won, and "best_hit" your hardest hit ever.
BADGES = (
    ("matches", "🎮", "Regular", "matches", (1, 10, 50, 200, 1000), "Play {n} [match|matches]"),
    ("wins", "🏆", "Winner", "wins", (1, 10, 50, 200, 500), "Win {n} [match|matches]"),
    ("kos", "💥", "Bonker", "kos", (1, 25, 100, 500, 2000), "Knock out {n} [ball|balls]"),
    ("first_blood", "🎯", "First Bonk", "feats.first_blood", (1, 10, 50, 200),
     "Make the first knockout of {n} [match|matches]"),
    ("double", "✌️", "Double Bonk", "feats.double", (1, 10, 50, 200),
     "{n} double [knockout|knockouts]: two within 3 seconds"),
    ("triple", "🔥", "Triple Bonk", "feats.triple", (1, 5, 25, 100),
     "{n} triple [knockout|knockouts]: three, each within 3 seconds"),
    ("super_ko", "🦸", "Super Smasher", "feats.super_ko", (1, 10, 50, 200),
     "Knock out {n} [ball|balls] with a super power"),
    ("flawless", "🛡️", "Untouchable", "feats.flawless", (1, 10, 50),
     "Win {n} [match|matches] without being knocked out"),
    ("best_hit", "🔨", "Wrecking Ball", "best_hit", (15, 25, 35), "Hit someone with power {n}"),
    ("pickups", "🍬", "Power Hungry", "pickups", (10, 100, 500), "Grab {n} [power-up|power-ups]"),
    ("awards", "⭐", "Showstopper", "awards", (5, 50, 250), "Win {n} end-of-match [award|awards]"),
    ("maps", "🗺️", "Explorer", "maps", (3, 5, len(MAPS)), "Play on {n} different [map|maps]"),
    ("modes", "🎲", "All-Rounder", "modes", (3, len(modes.MODES)), "Play {n} different [mode|modes]"),
    ("falls", "🧈", "Butterfingers", "falls", (10, 100, 500), "Fall off {n} [time|times] all by yourself"),
)


def describe():
    """The badges, for the page."""
    return [{"id": i, "icon": icon, "title": title, "stat": stat, "levels": list(levels), "goal": goal}
            for i, icon, title, stat, levels, goal in BADGES]


def value(stats, stat):
    """What a badge counts, from a profile's stats."""
    if stat.startswith("feats."):
        return stats.get("feats", {}).get(stat[6:], 0)
    if stat in ("maps", "modes"):
        return sum(1 for t in stats.get(stat, {}).values() if t.get("matches"))
    if stat == "awards":
        return sum(stats.get("awards", {}).values())
    return stats.get(stat, 0)


def level(stats, badge):
    """How many of a badge's levels (describe()'s entries) the stats reach."""
    v = value(stats, badge["stat"])
    return sum(1 for n in badge["levels"] if v >= n)
