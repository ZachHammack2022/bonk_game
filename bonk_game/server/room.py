"""Rooms: a lobby of people who share a link, and the matches they play.

A room has members (people with the page open), a host who picks the
settings, and at most one match at a time. Everyone connected when the
host presses Start plays (up to 10); bots fill the slots the host added.
People who join during a match watch it and play in the next one.

Each browser has a token (kept in its localStorage), so a refresh or a
dropped connection puts you back in your seat. While you're gone a
Medium bot plays for you; if you don't come back within LEAVE_GRACE
seconds you leave the room.

Nothing here touches sockets directly: each member has an async `send`
function that takes a message dict.
"""
import asyncio
import json
import random
import time

from bonk_game.envs.utils import arena
from bonk_game.server import limits
from bonk_game.envs.utils.maps import MAPS
from bonk_game.server import modes
from bonk_game.server.match import BOT_KINDS, TICK_HZ, Match, is_bot
from bonk_game.ui import theme

ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I or O
ROOM_CODE_LEN = 4
LEAVE_GRACE = 30.0       # seconds a disconnected member keeps their place
EMPTY_ROOM_TTL = 600.0   # seconds an empty room is kept around
NAME_LEN = 16
FIRST_TO_RANGE = (1, 100)
EMOTES = 4               # emote ids 0-3 (the client picks the pictures)
EMOTE_GAP = 0.8          # seconds between one person's emotes
DEFAULT_MAP = "platform"
# Room settings besides the map, mode and goal
ROUND_TIMES = (None, 0, 20, 30, 45, 60, 90)   # seconds before sudden death; None: the map's own
GRAVITY = {"low": 0.6, "normal": 1.0, "high": 1.4}


class RoomFull(Exception):
    """Can't join: the room is full, or the host removed you."""


class ServerFull(Exception):
    pass


def clean_name(name):
    name = " ".join(str(name or "").split())[:NAME_LEN]
    return name or "Player"


class Member:
    def __init__(self, token, name, send):
        self.token = token
        self.name = name
        self.send = send
        self.connected = True
        self.left_at = None
        self.color = None       # colour they picked (index), if any
        self.team = None        # team they picked (0 or 1) in the teams mode, if any
        self.last_emote = 0.0


class Room:
    def __init__(self, code, agents=None):
        """agents: optional AgentStore for trained agents (see web.py)."""
        self.code = code
        self.agents = agents
        self.members = {}          # token -> Member, in join order
        self.host = None
        self.settings = {"map": DEFAULT_MAP, "first_to": 5, "bots": ["bot:medium"],
                         "mode": modes.DEFAULT_MODE, "round_time": None, "gravity": "normal"}
        self.match = None
        self.match_tokens = []     # slot -> member token (None for bots)
        self.results = None
        self.task = None
        self.banned = set()        # tokens the host removed
        self.votes = set()         # tokens that want a rematch (on the results screen)
        self.created = time.monotonic()
        self.empty_since = time.monotonic()

    # --- membership ---------------------------------------------------------
    @property
    def connected(self):
        return [m for m in self.members.values() if m.connected]

    async def join(self, token, name, send):
        """Add (or reconnect) a member. Returns the Member."""
        if token in self.banned:
            raise RoomFull("The host removed you from this room.")
        m = self.members.get(token)
        if m is None:
            if len(self.members) >= limits.MAX_MEMBERS:
                raise RoomFull("This room is full.")
            m = Member(token, clean_name(name), send)
            self.members[token] = m
        else:
            m.send, m.connected, m.left_at = send, True, None
            if name:
                m.name = clean_name(name)
        if self.host is None or self.host not in self.members:
            self.host = token
        self.empty_since = None
        await m.send(self.welcome(token))
        if self.match is not None and token in self.match_tokens:
            self.match.release(self.match_tokens.index(token))
        if self.match is not None:
            await m.send(self.match.describe())
        elif self.results is not None:
            await m.send(self.results)
        await self.broadcast_lobby()
        return m

    async def disconnect(self, token, send=None):
        """`send`: the connection that closed. If the member has already
        reconnected on a newer one (a refresh), nothing changes."""
        m = self.members.get(token)
        if m is None or (send is not None and m.send is not send):
            return
        m.connected = False
        m.left_at = time.monotonic()
        if self.match is not None and token in self.match_tokens:
            self.match.stand_in(self.match_tokens.index(token))
        if self.host == token:
            self._pick_host()
        if not self.connected:
            self.empty_since = time.monotonic()
        self.votes.discard(token)
        await self.broadcast_lobby()
        await self._maybe_rematch()

    def _pick_host(self):
        """Hand the host role to the first connected member (if any)."""
        live = self.connected
        if live:
            self.host = live[0].token

    async def prune(self, now=None):
        """Drop members who've been gone longer than LEAVE_GRACE."""
        now = time.monotonic() if now is None else now
        gone = [t for t, m in self.members.items()
                if not m.connected and now - m.left_at > LEAVE_GRACE]
        for t in gone:
            del self.members[t]
        if self.host not in self.members:
            live = self.connected
            self.host = live[0].token if live else next(iter(self.members), None)
        if gone:
            await self.broadcast_lobby()

    def expired(self, now=None):
        now = time.monotonic() if now is None else now
        return (not self.connected and self.empty_since is not None
                and now - self.empty_since > EMPTY_ROOM_TTL)

    # --- messages out -------------------------------------------------------
    def bot_options(self):
        names = list(self.agents.names(self.settings["map"])) if self.agents else []
        return list(BOT_KINDS) + names

    def welcome(self, token):
        return {
            "type": "welcome",
            "room": self.code,
            "you": token,
            "max_players": arena.MAX_PLAYERS,
            "colors": ["#%02x%02x%02x" % c for c in theme.PLAYER_COLORS],
            "color_names": list(theme.PLAYER_NAMES),
            "maps": [{"name": n, "title": MAPS[n].title, "description": MAPS[n].description,
                      "first_to": min(MAPS[n].winning_score, 10), "round_time": MAPS[n].round_time,
                      "respawn_ok": MAPS[n].respawn_ok}
                     for n in map_order()],
            "modes": modes.describe_modes(),
            "round_times": list(ROUND_TIMES),
            "gravities": list(GRAVITY),
            "team_names": list(modes.TEAM_NAMES),
            "team_colors": list(modes.TEAM_HEX),
            "team_size": modes.TEAM_SIZE,
            "team_palettes": [list(c) for c in modes.TEAM_COLORS],
        }

    def lobby(self):
        return {
            "type": "lobby",
            "room": self.code,
            "host": self.host,
            "members": [{"id": m.token, "name": m.name, "connected": m.connected}
                        for m in self.members.values()],
            "settings": self.settings,
            "bot_options": self.bot_options(),
            "phase": "match" if self.match is not None else "results" if self.results else "lobby",
            "playing": list(self.match_tokens) if self.match is not None else [],
            "seats": self.lineup(),
            "votes": sorted(self.votes),
        }

    async def broadcast(self, msg):
        text = msg if isinstance(msg, str) else json.dumps(msg, separators=(",", ":"))
        live = self.connected
        if live:
            await asyncio.gather(*(m.send(text) for m in live), return_exceptions=True)

    async def broadcast_lobby(self):
        await self.broadcast(self.lobby())

    async def error(self, token, text):
        m = self.members.get(token)
        if m is not None and m.connected:
            await m.send({"type": "error", "message": text})

    # --- messages in --------------------------------------------------------
    async def handle(self, token, msg):
        kind = msg.get("type")
        if kind == "input":
            if self.match is not None and token in self.match_tokens:
                b = msg.get("b")
                if isinstance(b, list) and len(b) == 5:
                    self.match.set_input(self.match_tokens.index(token), b)
            return
        if kind == "ping":
            m = self.members.get(token)
            if m is not None:
                await m.send({"type": "pong", "t": msg.get("t")})
            return
        if kind == "name":
            self.members[token].name = clean_name(msg.get("name"))
            await self.broadcast_lobby()
            return
        if kind == "color":
            problem = self.pick_color(token, msg.get("color"))
            if problem:
                await self.error(token, problem)
            await self.broadcast_lobby()
            return
        if kind == "team":
            problem = self.pick_team(token, msg.get("team"))
            if problem:
                await self.error(token, problem)
            await self.broadcast_lobby()
            return
        if kind == "emote":
            await self.emote(token, msg.get("id"))
            return
        if kind == "vote":
            if self.match is None and self.results is not None:
                self.votes.symmetric_difference_update({token})
                await self.broadcast_lobby()
                await self._maybe_rematch()
            return
        if token != self.host:
            await self.error(token, "Only the host can do that.")
            return
        if kind == "settings":
            problem = self.update_settings(msg)
            if problem:
                await self.error(token, problem)
            await self.broadcast_lobby()
        elif kind == "start":
            await self.start()
        elif kind == "lobby":
            if self.match is None:
                self.results = None
                self.votes.clear()
                await self.broadcast_lobby()
        elif kind == "kick":
            await self.kick(str(msg.get("id")))

    # --- people -------------------------------------------------------------
    def pick_color(self, token, color):
        """Someone picks their colour (an index), or None for "any"."""
        if color is not None:
            if not isinstance(color, int) or not 0 <= color < arena.MAX_PLAYERS:
                return "Unknown colour."
            if any(m.color == color for t, m in self.members.items() if t != token):
                return "Someone else has that colour."
        self.members[token].color = color
        return None

    def pick_team(self, token, team):
        """Someone picks a side in the teams mode (0 or 1), or None for "either"."""
        if team is not None and team not in (0, 1):
            return "Unknown team."
        self.members[token].team = team
        return None

    async def emote(self, token, emote):
        """Show an emote over someone's ball (during a match)."""
        m = self.members.get(token)
        if (self.match is None or token not in self.match_tokens or not isinstance(emote, int)
                or not 0 <= emote < EMOTES):
            return
        now = time.monotonic()
        if now - m.last_emote < EMOTE_GAP:
            return
        m.last_emote = now
        await self.broadcast({"type": "emote", "slot": self.match_tokens.index(token), "id": emote})

    async def kick(self, token):
        """The host removes someone. They can't come back to this room."""
        m = self.members.get(token)
        if m is None or token == self.host:
            return
        self.banned.add(token)
        if m.connected:
            await m.send({"type": "error", "message": "The host removed you from this room.",
                          "fatal": True})
        if self.match is not None and token in self.match_tokens:
            self.match.stand_in(self.match_tokens.index(token))
        del self.members[token]
        self.votes.discard(token)
        await self.broadcast_lobby()

    async def _maybe_rematch(self):
        """On the results screen, start again once everyone here has voted."""
        live = {m.token for m in self.connected}
        if self.match is None and self.results is not None and live and live <= self.votes:
            await self.start()

    def update_settings(self, msg):
        """Apply the host's changes. Returns an error message or None."""
        if self.match is not None:
            return "Settings can't change during a match."
        s = dict(self.settings)
        if "mode" in msg:
            if msg["mode"] not in modes.MODES:
                return "Unknown mode."
            if msg["mode"] != s["mode"]:
                s["first_to"] = default_goal(msg["mode"], s["map"])
            s["mode"] = msg["mode"]
        if "map" in msg:
            if msg["map"] not in MAPS:
                return "Unknown map."
            if msg["map"] != s["map"] and modes.MODES[s["mode"]].goal_label == "First to":
                s["first_to"] = default_goal(s["mode"], msg["map"])
            s["map"] = msg["map"]
        mode = modes.MODES[s["mode"]]
        if mode.respawns and not MAPS[s["map"]].respawn_ok and "map" not in msg:
            # Picked a respawn mode on a map that can't do it: move to one that can
            s["map"] = next(n for n in map_order() if MAPS[n].respawn_ok)
        if mode.respawns and not MAPS[s["map"]].respawn_ok:
            return f"{mode.title} needs a map where you can respawn: {MAPS[s['map']].title} isn't one."
        if "first_to" in msg:
            try:
                ft = int(msg["first_to"])
            except (TypeError, ValueError):
                return "First to should be a number."
            s["first_to"] = max(FIRST_TO_RANGE[0], min(FIRST_TO_RANGE[1], ft))
        if "round_time" in msg:
            if msg["round_time"] not in ROUND_TIMES:
                return "Unknown round time."
            s["round_time"] = msg["round_time"]
        if "gravity" in msg:
            if msg["gravity"] not in GRAVITY:
                return "Unknown gravity."
            s["gravity"] = msg["gravity"]
        self.settings = s
        options = self.bot_options()
        if "bots" in msg:
            bots = msg["bots"]
            if not isinstance(bots, list) or any(b not in options for b in bots):
                return "Unknown bot."
            s["bots"] = bots[:arena.MAX_PLAYERS - 1]
        # Agents trained for another map can't play this one
        s["bots"] = [b if b in options else "bot:medium" for b in s["bots"]]
        return None

    # --- matches ------------------------------------------------------------
    def seats(self):
        """Who would play if the match started now: (member tokens, bot kinds)."""
        humans = [m.token for m in self.connected][:arena.MAX_PLAYERS]
        bots = self.settings["bots"][:arena.MAX_PLAYERS - len(humans)]
        return humans, bots

    def teams_for(self, humans, n_bots):
        """A team per seat in the teams mode (else None): people get the side
        they picked while it has room; everyone else evens the teams out."""
        if self.settings["mode"] != "teams":
            return None
        out, size = [], [0, 0]
        for t in humans:
            pick = self.members[t].team
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

    def colors_for(self, humans, n_bots, teams=None):
        """A colour index per seat: people get the colour they picked (first
        come, first served), everyone else the free colours in order. In the
        teams mode each side has its own colours (modes.TEAM_COLORS)."""
        palette = lambda k: (modes.TEAM_COLORS[teams[k]] if teams is not None
                             else range(arena.MAX_PLAYERS))
        out, taken = [], set()
        for k, t in enumerate(humans):
            c = self.members[t].color
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

    def lineup(self):
        """The seats as they'd be if the match started now, for the lobby."""
        humans, bots = self.seats()
        teams = self.teams_for(humans, len(bots))
        colors = self.colors_for(humans, len(bots), teams)
        team = lambda k: None if teams is None else teams[k]
        seats = [{"id": t, "name": self.members[t].name, "kind": "human", "color": c, "team": team(k)}
                 for k, (t, c) in enumerate(zip(humans, colors))]
        seats += [{"id": None, "kind": b, "bot": k, "color": c, "team": team(len(humans) + k)}
                  for k, (b, c) in enumerate(zip(bots, colors[len(humans):]))]
        return seats

    async def start(self):
        if self.match is not None:
            return
        humans, bots = self.seats()
        if len(humans) + len(bots) < arena.MIN_PLAYERS:
            await self.error(self.host, "Add a bot or invite someone: a match needs 2 players.")
            return
        teams = self.teams_for(humans, len(bots))
        colors = self.colors_for(humans, len(bots), teams)
        slots = [{"kind": "human", "name": self.members[t].name, "id": t, "color": c}
                 for t, c in zip(humans, colors)]
        # Bots are named by colour ("Green bot"), which is easier to follow than
        # five "Medium bot"s
        slots += [{"kind": b, "color": c,
                   "name": f"{theme.PLAYER_NAMES[c]} {bot_label(b, short=True)}"}
                  for b, c in zip(bots, colors[len(humans):])]
        for k, slot in enumerate(slots):
            if teams is not None:
                slot["team"] = teams[k]
        agents = {}
        agent_kinds = [b for b in bots if not is_bot(b)]
        if agent_kinds:
            agents = self.agents.load(self.settings["map"])
        s = self.settings
        mode = modes.MODES[s["mode"]]
        if mode.respawns and not MAPS[s["map"]].respawn_ok:
            await self.error(self.host, f"{mode.title} doesn't work on {MAPS[s['map']].title}.")
            return
        self.match = Match(s["map"], slots, s["first_to"], agents, mode=s["mode"],
                           round_time=s["round_time"] if mode.uses_round_time else None,
                           gravity=GRAVITY[s["gravity"]])
        self.match_tokens = humans + [None] * len(bots)
        self.results = None
        self.votes.clear()
        await self.broadcast(self.match.describe())
        await self.broadcast_lobby()
        self.task = asyncio.ensure_future(self.run_match())

    async def run_match(self):
        """Step the match 30 times a second and send everyone the state."""
        match = self.match
        loop = asyncio.get_running_loop()
        next_t = loop.time()
        try:
            while not match.finished:
                events = match.tick()
                state = match.snapshot()
                state["events"] = events
                await self.broadcast(state)
                next_t += 1 / TICK_HZ
                delay = next_t - loop.time()
                if delay < -0.25:
                    next_t = loop.time()  # fell far behind: don't try to catch up
                await asyncio.sleep(max(0.0, delay))
                if not self.connected:
                    break  # everyone left: stop simulating
            self.results = match.results()
            self.results["slots"] = match.describe()["slots"]
        finally:
            self.match = None
            self.match_tokens = []
            self.task = None
        await self.broadcast(self.results)
        await self.broadcast_lobby()

    async def stop(self):
        if self.task is not None:
            self.task.cancel()


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
    first = ["platform", "slider", "swing", "ramps", "classic"]
    return [n for n in first if n in MAPS] + sorted(n for n in MAPS if n not in first)


class RoomManager:
    def __init__(self, agents=None, rng=None):
        self.rooms = {}
        self.agents = agents
        self.rng = rng or random.Random()

    def create(self):
        if len(self.rooms) >= limits.MAX_ROOMS:
            raise ServerFull()
        for _ in range(1000):
            code = "".join(self.rng.choice(ROOM_ALPHABET) for _ in range(ROOM_CODE_LEN))
            if code not in self.rooms:
                self.rooms[code] = Room(code, self.agents)
                return self.rooms[code]
        raise RuntimeError("no free room codes")

    def get(self, code):
        return self.rooms.get((code or "").upper())

    async def sweep(self):
        """Drop departed members and expired rooms. Run every few seconds."""
        now = time.monotonic()
        for code, room in list(self.rooms.items()):
            await room.prune(now)
            if room.expired(now):
                await room.stop()
                del self.rooms[code]
