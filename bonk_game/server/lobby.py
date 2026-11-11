"""The lobby's rules: what the host may set, and who sits where.

Plain functions of a room's settings and the people in it, so they can be
tested (and read) without a Room. room.py calls them.

- check_settings(): apply the host's changes, or say what's wrong.
- seats(): who would play if the match started now (people first, then
  bots, as many as the map takes).
- teams_for() / colors_for(): each seat's team and colour, honouring what
  people picked where possible.
- lineup(): the seats as the lobby shows them.
"""
import math
import re
import secrets

from bonk_game.envs.utils import arena, stepping
from bonk_game.envs.utils.maps import MAPS
from bonk_game.server import cosmetics, moderation, modes, powerups
from bonk_game.server.match import is_bot
from bonk_game.ui import theme

NAME_LEN = moderation.NAME_LEN
FIRST_TO_RANGE = (1, 100)
# Ball patterns people can pick (the client draws them; cosmetics.py)
PATTERNS = cosmetics.IDS["pattern"]
# A colour of your own has to be at least this far (in RGB) from everyone
# else's, so balls stay easy to tell apart
MIN_COLOR_GAP = 70
HEX_COLOR = re.compile(r"^#[0-9a-f]{6}$")
DEFAULT_MAP = "swing"  # (Sinking Swing: new rooms start on it)
# Room settings besides the map, mode and goal
ROUND_TIMES = (None, 0, 20, 30, 45, 60, 90)   # seconds before sudden death; None: the map's own
GRAVITY = {"low": 0.6, "normal": 1.0, "high": 1.4}
# Game speed: how fast the world runs (stepping.TIME_SCALE). Normal is a bit
# slower than the original, which is "fast"
SPEEDS = {"slow": 0.6, "normal": stepping.TIME_SCALE, "fast": 1.0}
QUICK_BOTS = 3   # bots in a room Quick play makes
QUICK_FILL = 4   # and they make it up to this many players: one bot steps aside for each person past 1
# Room names (shown in the game browser) and passwords. Every room is listed;
# one with a password needs it to get in (the invite link carries it)
ROOM_NAME_LEN = 30
PASSWORD_LEN = (1, 20)
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no i, l, o, 0 or 1
NEW_PASSWORD_LEN = 6


def new_password():
    """A random room password, easy to read out ("k7mq2x")."""
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(NEW_PASSWORD_LEN))


def default_settings():
    """name: the room's name in the game browser (None: "<host>'s room").
    password: needed to join (None: anyone can). Every room is listed."""
    return {"map": DEFAULT_MAP, "first_to": 5, "bots": ["bot:medium"],
            "mode": modes.DEFAULT_MODE, "round_time": None, "gravity": "normal", "speed": "normal",
            "power_ups": False, "power_kinds": list(powerups.ALL_KINDS), "name": None, "password": None}


def quick_settings():
    """A room Quick play makes when no open room has space: Knockouts
    (people can drop in at any time) on Platform, with bots to play against.
    (Not Sinking Swing: its floor is gone by the end of a round, so nobody
    could respawn, and Knockouts needs that.)"""
    return {**default_settings(), "map": "platform", "mode": "knockouts",
            "first_to": modes.MODES["knockouts"].goal_default, "bots": ["bot:medium"] * QUICK_BOTS}


def clean_room_name(name):
    """A room name to use (tidied, cut to ROOM_NAME_LEN), or None for the
    default, if it's empty or offensive."""
    name = " ".join(str(name or "").split())[:ROOM_NAME_LEN]
    if not name or moderation.offensive(name):
        return None
    return name


def clean_password(password):
    """A password to use, or None if it isn't one (not a string, or too
    short or long once trimmed)."""
    if not isinstance(password, str):
        return None
    password = password.strip()
    return password if PASSWORD_LEN[0] <= len(password) <= PASSWORD_LEN[1] else None


def room_title(settings, host_name):
    """What the game browser calls the room."""
    return settings.get("name") or (f"{host_name}'s room" if host_name else "Open room")


def clean_name(name):
    """Tidied, and not offensive (moderation.py)."""
    return moderation.clean_name(name)[0]


def bot_label(kind, short=False):
    """"Medium bot" / "PPO" (short: "bot" / "PPO")."""
    if is_bot(kind):
        return "bot" if short else f"{kind.split(':', 1)[1].title()} bot"
    return kind.upper()


def default_goal(mode, map_name):
    if modes.MODES[mode].goal_label == "First to":
        return min(MAPS[map_name].winning_score, 10)
    return modes.MODES[mode].goal_default


def map_order():
    first = ["swing", "platform", "slider", "ramps", "classic"]
    return [n for n in first if n in MAPS] + sorted(n for n in MAPS if n not in first)


def check_settings(settings, msg, people, bot_options):
    """The host's changes (`msg`) applied to `settings`: (new settings,
    None), or (settings as far as they got, an error message). `people`:
    how many are connected; `bot_options()`: the bots and agents that can
    play the map in the given settings."""
    s = dict(settings)
    if "mode" in msg:
        if msg["mode"] not in modes.MODES:
            return settings, "Unknown mode."
        if msg["mode"] != s["mode"]:
            s["first_to"] = default_goal(msg["mode"], s["map"])
        s["mode"] = msg["mode"]
    if "map" in msg:
        if msg["map"] not in MAPS:
            return settings, "Unknown map."
        most = MAPS[msg["map"]].players[1]
        if people > most:
            return settings, (f"{MAPS[msg['map']].title} is for up to {most} players, "
                              f"and there are {people} here.")
        if msg["map"] != s["map"] and modes.MODES[s["mode"]].goal_label == "First to":
            s["first_to"] = default_goal(s["mode"], msg["map"])
        s["map"] = msg["map"]
    mode = modes.MODES[s["mode"]]
    if mode.respawns and not MAPS[s["map"]].respawn_ok and "map" not in msg:
        # Picked a respawn mode on a map that can't do it: move to one that can
        s["map"] = next(n for n in map_order() if MAPS[n].respawn_ok)
    if mode.respawns and not MAPS[s["map"]].respawn_ok:
        return settings, f"{mode.title} needs a map where you can respawn: {MAPS[s['map']].title} isn't one."
    if "first_to" in msg:
        try:
            ft = int(msg["first_to"])
        except (TypeError, ValueError):
            return settings, "First to should be a number."
        s["first_to"] = max(FIRST_TO_RANGE[0], min(FIRST_TO_RANGE[1], ft))
    if "round_time" in msg:
        rt = msg["round_time"]
        if (rt is not None and type(rt) is not int) or rt not in ROUND_TIMES:
            return settings, "Unknown round time."
        s["round_time"] = msg["round_time"]
    if "power_ups" in msg:
        if not isinstance(msg["power_ups"], bool):
            return settings, "Power-ups should be on or off."
        s["power_ups"] = msg["power_ups"]
    if "power_kinds" in msg:
        kinds = msg["power_kinds"]
        if not isinstance(kinds, list) or any(not isinstance(k, str) or k not in powerups.KINDS for k in kinds):
            return settings, "Unknown power-up."
        if not kinds:
            return settings, "Pick at least one power-up."
        s["power_kinds"] = powerups.clean_kinds(kinds)
    if "name" in msg:
        if msg["name"] is not None and not isinstance(msg["name"], str):
            return settings, "The room's name should be text."
        s["name"] = clean_room_name(msg["name"])
    if "password" in msg:
        # Made up by the server (true: private, with a new one), never typed in
        if msg["password"] is True:
            s["password"] = new_password()
        elif msg["password"] in (None, False):
            s["password"] = None
        else:
            return settings, "Switch the room to private for a password."
    if "gravity" in msg:
        if msg["gravity"] not in GRAVITY:
            return settings, "Unknown gravity."
        s["gravity"] = msg["gravity"]
    if "speed" in msg:
        if msg["speed"] not in SPEEDS:
            return settings, "Unknown speed."
        s["speed"] = msg["speed"]
    # (From here on the map and the rest are kept even if the bots are wrong)
    options = bot_options(s)
    problem = None
    if "bots" in msg:
        bots = msg["bots"]
        if not isinstance(bots, list) or any(b not in options for b in bots):
            problem = "Unknown bot."
        else:
            s["bots"] = bots[:arena.MAX_PLAYERS - 1]
    # Agents trained for another map can't play this one
    s["bots"] = [b if b in options else "bot:medium" for b in s["bots"]]
    return s, problem


def seats(settings, people, fill=None):
    """Who would play if the match started now: (member tokens, bot kinds).
    `people`: the connected members' tokens, in join order. The map says how
    many can play; bots past that sit this one out, and so do people (they
    watch). `fill` (Quick play rooms): bots only make the players up to that
    many, so they step aside as people come."""
    most = MAPS[settings["map"]].players[1]
    humans = list(people)[:most]
    room = most - len(humans) if fill is None else min(most, fill) - len(humans)
    bots = settings["bots"][:max(0, room)]
    return humans, bots


def teams_for(mode, picks, n_bots):
    """A team per seat in the teams mode (else None). `picks`: the team each
    person picked (or None), in seat order. People get the side they picked
    while it has room; everyone else evens the teams out."""
    if mode != "teams":
        return None
    out, size = [], [0, 0]
    for pick in picks:
        if pick is not None and size[pick] < modes.TEAM_SIZE:
            size[pick] += 1
            out.append(pick)
        else:
            out.append(None)
    for k in range(len(out)):
        if out[k] is None:
            out[k] = 0 if size[0] <= size[1] else 1
            size[out[k]] += 1
    for _ in range(n_bots):
        out.append(0 if size[0] <= size[1] else 1)
        size[out[-1]] += 1
    return out


def colors_for(picks, n_bots, teams=None):
    """A colour index per seat. `picks`: the colour each person picked (or
    None), in seat order. People get the colour they picked (first come,
    first served), everyone else the free colours in order. In the teams
    mode each side has its own colours (modes.TEAM_COLORS)."""
    palette = lambda k: (modes.TEAM_COLORS[teams[k]] if teams is not None
                         else range(arena.MAX_PLAYERS))
    out, taken = [], set()
    for k, c in enumerate(picks):
        ok = c is not None and c not in taken and c in palette(k)
        out.append(c if ok else None)
        if ok:
            taken.add(c)
    out += [None] * n_bots
    for k, c in enumerate(out):
        if c is None:
            out[k] = next(c for c in palette(k) if c not in taken)
            taken.add(out[k])
    return out


def _rgb(hex_color):
    return tuple(int(hex_color[k:k + 2], 16) for k in (1, 3, 5))


def own_colors(colors, wanted, teams=None):
    """People's own colours, where they can have them: a hex
    colour per seat, or None to use the palette colour (colors[k], an index
    into theme.PLAYER_COLORS). `wanted`: each seat's own colour (or None).
    Not in the teams mode (colours show your side), and not if it's close to
    a colour someone else has (first come, first served)."""
    out = [None] * len(colors)
    if teams is not None:
        return out
    taken = [theme.PLAYER_COLORS[c][:3] for k, c in enumerate(colors) if not wanted[k]]
    for k, w in enumerate(wanted):
        if not w:
            continue
        rgb = _rgb(w)
        if all(math.dist(rgb, t) >= MIN_COLOR_GAP for t in taken):
            out[k] = w
            taken.append(rgb)
    return out


def lineup(settings, members, people, fill=None):
    """The seats as they'd be if the match started now, for the lobby.
    `members`: token -> Member; `people`: the connected members' tokens.
    People are shown by their public id (Member.pid), never their token."""
    humans, bots = seats(settings, people, fill)
    teams = teams_for(settings["mode"], [members[t].team for t in humans], len(bots))
    colors = colors_for([members[t].color for t in humans], len(bots), teams)
    own = own_colors(colors, [members[t].own_color for t in humans] + [None] * len(bots), teams)
    team = lambda k: None if teams is None else teams[k]
    out = [{"id": members[t].pid, "name": members[t].name, "kind": "human", "color": c, "team": team(k),
            **members[t].look(), "own_color": own[k]}
           for k, (t, c) in enumerate(zip(humans, colors))]
    out += [{"id": None, "kind": b, "bot": k, "color": c, "team": team(len(humans) + k)}
            for k, (b, c) in enumerate(zip(bots, colors[len(humans):]))]
    return out
