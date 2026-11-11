"""Rooms: a lobby of people who share a link, and the matches they play.

A room has members (people with the page open), a host who picks the
settings, and at most one match at a time. Everyone connected when the
host presses Start plays (up to 10); bots fill the slots the host added.
People who join during a match watch it and play in the next one.

Each browser has a token (kept in its localStorage), so a refresh or a
dropped connection puts you back in your seat. The token is a secret: the
others see you by a public id (Member.pid) instead, so nobody can take
your seat (or the host's) by copying it. While you're gone a
Medium bot plays for you; if you don't come back within LEAVE_GRACE
seconds you leave the room. The Leave button (or Back in the browser)
leaves straight away.

Nothing here touches sockets directly: each member has an async `send`
function that takes a message dict.

Every room is listed in the game browser, by its name (settings "name";
"<host>'s room" if none). A room with a password (settings "password",
made up when the room is) needs it to get in: the invite link carries it,
and people already in the room don't need it again to reconnect. Quick play
(RoomManager.quick_play) sends you to the open room (no password) with the
most people and space for you, or makes one with bots that starts by
itself ("quick"); its bots step aside as people come (lobby.QUICK_FILL). Someone who joins during a match
takes over a bot's seat: straight away in modes where balls respawn, at
the next round in the others. With no bot to take over, they watch and
play in the next match.

The lobby's rules (settings, seats, teams, colours) are in lobby.py, what
happens to playtest reports in playtest.py, and the name filter and
player reports in moderation.py.
"""
import asyncio
import collections
import hmac
import json
import logging
import random
import secrets
import time
import traceback

from bonk_game.envs.utils import arena
from bonk_game.envs.utils.maps import MAPS, make_map
from bonk_game.server import (cosmetics, delta, limits, lobby, metrics, moderation, modes, playtest,
                              powerups, profiles)
from bonk_game.server.lobby import GRAVITY, HEX_COLOR, PATTERNS, ROUND_TIMES, SPEEDS, bot_label, map_order
from bonk_game.server.match import BOT_KINDS, TICK_HZ, Match, is_bot
from bonk_game.server.scene import level_shapes
from bonk_game.ui import theme

ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I or O
ROOM_CODE_LEN = 4
LEAVE_GRACE = 30.0       # seconds a disconnected member keeps their place
REOPEN_GRACE = 30.0      # after a restart, seconds the old host has to claim the room back
EMPTY_ROOM_TTL = 600.0   # seconds an empty room is kept around
EMOTES = 4               # emote ids 0-3 (the client picks the pictures)
EMOTE_GAP = 0.8          # seconds between one person's emotes
AUTO_START = 2.0         # quick-play rooms: seconds from someone joining to the match starting
AUTO_NEXT = 10.0         # and from the results to the next match
LISTED = 200             # rooms the game browser lists (it filters and pages them)
CHAT_KEPT = 50           # chat lines a room keeps, for people who join
CHAT_RATE = 0.5          # chat messages a second, per person, on average
CHAT_BURST = 5           # and in a burst


_PREVIEWS = {}


def map_preview(name):
    """The shapes a map starts with, for the lobby's picture of it (made once)."""
    if name not in _PREVIEWS:
        _PREVIEWS[name] = level_shapes(make_map(name))
    return _PREVIEWS[name]


class RoomFull(Exception):
    """Can't join: the room is full, or the host removed you."""


class PasswordNeeded(RoomFull):
    """The room has a password, and it wasn't given (wrong: a wrong one was)."""

    def __init__(self, wrong):
        super().__init__("Wrong password." if wrong else "This game is private: it needs its password.")
        self.wrong = wrong


class ServerFull(Exception):
    """No new room: the server has as many as it takes, or it's busy (RoomManager.busy)."""


class ServerBusy(RoomFull):
    """Can't join: the server is busy (RoomManager.busy). Try again soon."""

    def __init__(self):
        super().__init__("The servers are busy right now.")


class Member:
    def __init__(self, token, name, send):
        self.token = token
        self.name = name
        self.send = send
        self.connected = True
        self.left_at = None
        self.color = None       # colour they picked (index), if any
        self.team = None        # team they picked (0 or 1) in the teams mode, if any
        self.pattern = "plain"  # pattern on their ball (PATTERNS)
        self.trail = "none"     # and the rest of what it wears (cosmetics.py)
        self.hat = "none"
        self.ko = "pop"
        self.last_emote = 0.0
        self.chat_bucket = limits.TokenBucket(CHAT_RATE, CHAT_BURST)
        self.last_report = None  # when they last sent a playtest report
        self.errors_sent = 0     # client errors logged for them
        self.account = None      # their account id, when signed in (accounts.py)
        self.rating = None       # their rating badge (rating.badge), when signed in
        self.tz = None           # their clock's offset from UTC in minutes, from their browser (badges)
        self.own_color = None    # a colour of their own ("#rrggbb"): signed in only
        self.pid = secrets.token_hex(4)  # how the others see them (the token is a secret)
        self.names = collections.deque([name], maxlen=5)  # names they've used here, for reports
        self.report_times = collections.deque(maxlen=moderation.REPORTS_PER_MINUTE)
        self.reported = set()    # pids they've reported
        self.watching = False    # came to watch (spectate): no seat, now or in the next match, until they ask
        self.region = None       # where their connection came in (Fly's region, e.g. "lhr"), for /admin
        self.rtt = None          # their round trip in ms, as their browser last said
        self.delay = None        # how far behind the newest states their match is drawn, ms (in a match)
        self.net = collections.deque(maxlen=120)  # (when, states, stalls) from each ping: see stall_window

    def note_network(self, now, msg):
        """What a ping says about their network (js/net.js): the round trip,
        and in a match the drawing delay and how many states came since the
        last ping (and how many of those after a stall). Anything that isn't
        a sensible number is ignored."""
        def number(v, hi):
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < hi else None
        rtt, delay = number(msg.get("rtt"), 10000), number(msg.get("delay"), 10000)
        states, stalled = number(msg.get("states"), 1000), number(msg.get("stalls"), 1000)
        if rtt is not None:
            self.rtt = round(rtt)
        if states:
            self.delay = None if delay is None else round(delay)
            self.net.append((now, int(states), int(min(stalled or 0, states))))
        else:
            self.delay = None  # (not in a match now)

    def stall_window(self, now, seconds=60):
        """(states, stalls) their browser counted over the last `seconds`."""
        recent = [(n, s) for t, n, s in self.net if now - t <= seconds]
        return sum(n for n, _ in recent), sum(s for _, s in recent)

    def rename(self, name):
        self.name = name
        if name not in self.names:
            self.names.append(name)

    def look(self):
        """What their ball wears, for the lobby and the match."""
        return {"pattern": self.pattern, "trail": self.trail, "hat": self.hat, "ko": self.ko}


class Room:
    def __init__(self, code, agents=None, recorder=None, profile_of=None):
        """agents: optional AgentStore for trained agents (see web.py).
        recorder(account, entry): adds a match to a signed-in player's
        history (accounts.Accounts.record), if accounts are on.
        profile_of(account): a signed-in player's profile (accounts.Accounts.
        profile), for what they've unlocked (cosmetics.py)."""
        self.code = code
        self.agents = agents
        self.recorder = recorder
        self.profile_of = profile_of
        self.members = {}          # token -> Member, in join order
        self.host = None
        self.settings = lobby.default_settings()
        self.match = None
        self.match_tokens = []     # slot -> member token (None for bots)
        self.results = None
        self.task = None
        self.ending = None  # who ended the match early (the host's name), until it stops
        self.encoder = None        # the match's state messages (delta.py)
        self.banned = set()        # tokens (and accounts) the host removed
        self.votes = set()         # tokens that want a rematch (on the results screen)
        self.closing = False       # the server is restarting: no new matches
        self.reopened_at = None    # made again after a server restart (see web.py)
        self.quick = False         # made by Quick play: matches start by themselves
        self.auto_task = None      # (the next one, when it's due)
        self.waiting = []          # tokens waiting to take over a bot's seat in this match
        self.match_accounts = []   # slot -> account of whoever plays it (for match history)
        self.rated_accounts = []   # slot -> account of who played it from the start (rated)
        self.ratings = None        # signed-in players' ratings and friends (accounts.Accounts)
        self.tell_account = None   # async (account, msg): tell them wherever they are (RoomManager)
        self.busy = None           # () -> why the server is busy, or None (RoomManager.busy)
        self.recent = collections.deque(maxlen=moderation.RECENT_KEPT)  # for reports
        self.chat = collections.deque(maxlen=CHAT_KEPT)  # the latest chat lines
        self.created = time.monotonic()
        self.empty_since = time.monotonic()

    # --- membership ---------------------------------------------------------
    @property
    def connected(self):
        return [m for m in self.members.values() if m.connected]

    @property
    def players(self):
        """The connected members who play (not the ones just watching)."""
        return [m for m in self.members.values() if m.connected and not m.watching]

    def token_of(self, pid):
        """The member with this public id's token, or None."""
        return next((t for t, m in self.members.items() if m.pid == pid), None)

    def pid(self, token):
        m = self.members.get(token)
        return m.pid if m is not None else None

    def note(self, event, **info):
        """Remember what happened, for reports (moderation.py)."""
        self.recent.append({"t": round(time.monotonic() - self.created), "e": event, **info})

    def _name(self, token, name):
        """A name to use, and a word with them (and the log) if it was
        replaced by the filter. Returns (name, notice or None)."""
        clean, replaced = moderation.clean_name(name)
        if not replaced:
            return clean, None
        metrics.event("name_filtered", logging.WARNING, room=self.code, name=str(name)[:40])
        self.note("name_filtered", name=str(name)[:40], now=clean)
        return clean, f"That name isn't allowed here, so you're {clean}."

    def password_ok(self, token, password):
        """May this browser come in? Yes without a password if the room has
        none, or they're already a member (back after a refresh)."""
        want = self.settings.get("password")
        if not want or token in self.members:
            return True
        return isinstance(password, str) and hmac.compare_digest(password.strip().encode(), want.encode())

    async def join(self, token, name, send, was_host=False, account=None, password=None, watch=False):
        """Add (or reconnect) a member. Returns the Member. was_host: they
        were the host before a server restart, and get it back if they come
        back soon after (whoever reconnects first doesn't keep it).
        account: their account id, if they're signed in. password: the
        room's password (PasswordNeeded if it has one and this isn't it).
        watch: they came to watch: they don't play until they ask ("play")."""
        if token in self.banned or (account is not None and account in self.banned):
            raise RoomFull("The host removed you from this room.")
        if not self.password_ok(token, password):
            raise PasswordNeeded(wrong=bool(password))
        m = self.members.get(token)
        notice = None
        joined = False
        if m is None:
            if len(self.members) >= limits.MAX_MEMBERS:
                raise RoomFull("This room is full.")
            # A busy server lets nobody new in (people already here can
            # always come back; so can a room's people after a restart)
            if self.busy is not None and self.reopened_at is None and self.busy():
                metrics.STATS.refused_busy += 1
                raise ServerBusy()
            clean, notice = self._name(token, name)
            m = Member(token, clean, send)
            self.members[token] = m
            joined = True
        else:
            m.send, m.connected, m.left_at = send, True, None
            if name:
                clean, notice = self._name(token, name)
                m.rename(clean)
        m.account = account
        m.rating = self._rating(account)
        m.watching = bool(watch) and not (self.match is not None and token in self.match_tokens)
        self.note("join", who=m.name, account=account)
        if self.host is None or self.host not in self.members:
            self.host = token
        if (was_host and self.reopened_at is not None
                and time.monotonic() - self.reopened_at < REOPEN_GRACE):
            self.host = token
            self.reopened_at = None  # only once
        self.empty_since = None
        await m.send(self.welcome(token))
        if notice:
            await m.send({"type": "notice", "message": notice})
        if self.match is not None and token in self.match_tokens:
            self.match.release(self.match_tokens.index(token))
        if self.match is not None:
            await m.send(self.match.describe())
            # The others get changes since the last tick; this one needs it all
            key = self.encoder.keyframe() if self.encoder else None
            if key is not None:
                await m.send(key)
        elif self.results is not None:
            await m.send(self.results)
        await self.broadcast_lobby()
        if joined:
            await self.say(f"{m.name} joined")  # (after "welcome", which has the chat so far)
        if self.match is not None and token not in self.match_tokens and not m.watching:
            await self.wait_for_seat(token)
        elif self.match is None and self.results is None:
            self.auto_start(AUTO_START)
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
        if token in self.waiting:
            self.waiting.remove(token)
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
            await self.say(f"{self.members.pop(t).name} left")
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
    def bot_options(self, settings=None):
        """The bots and trained agents that can play the map."""
        map_name = (settings or self.settings)["map"]
        names = list(self.agents.names(map_name)) if self.agents else []
        return list(BOT_KINDS) + names

    def welcome(self, token):
        return {
            "type": "welcome",
            "room": self.code,
            "you": self.members[token].pid,
            "max_players": arena.MAX_PLAYERS,
            "colors": ["#%02x%02x%02x" % c for c in theme.PLAYER_COLORS],
            "color_names": list(theme.PLAYER_NAMES),
            "patterns": list(PATTERNS),
            "signed_in": self.members[token].account is not None,
            "maps": [{"name": n, "title": MAPS[n].title, "description": MAPS[n].description,
                      "first_to": min(MAPS[n].winning_score, 10), "round_time": MAPS[n].round_time,
                      "respawn_ok": MAPS[n].respawn_ok, "players": list(MAPS[n].players),
                      "preview": map_preview(n)}
                     for n in map_order()],
            "modes": modes.describe_modes(),
            "round_times": list(ROUND_TIMES),
            # Power-ups a room can pick from
            "power_kinds": [{"id": k, "title": v["title"], "super": bool(v.get("super"))}
                            for k, v in powerups.KINDS.items()],
            "gravities": list(GRAVITY),
            "speeds": list(SPEEDS),
            "team_names": list(modes.TEAM_NAMES),
            "team_colors": list(modes.TEAM_HEX),
            "team_size": modes.TEAM_SIZE,
            "team_palettes": [list(c) for c in modes.TEAM_COLORS],
            "playtest": playtest.ENABLED,  # send playtest reports (playtest.py)
            "chat": list(self.chat),       # the latest chat lines
            "chat_len": moderation.CHAT_LEN,
        }

    def lobby(self):
        return {
            "type": "lobby",
            "room": self.code,
            "title": lobby.room_title(self.settings, self.members[self.host].name if self.host in self.members else None),
            "host": self.pid(self.host),
            "members": [{"id": m.pid, "name": m.name, "connected": m.connected,
                         **({"rating": m.rating} if m.rating else {}),
                         **({"signed_in": True} if m.account else {}),  # (friends need it)
                         **({"watching": True} if m.watching else {})}
                        for m in self.members.values()],
            "settings": self.settings,
            "bot_options": self.bot_options(),
            "phase": "match" if self.match is not None else "results" if self.results else "lobby",
            "playing": [self.pid(t) for t in self.match_tokens] if self.match is not None else [],
            "seats": self.lineup(),
            "votes": sorted(self.pid(t) for t in self.votes if t in self.members),
            "quick": self.quick,  # matches start by themselves
        }

    async def broadcast(self, msg):
        text = msg if isinstance(msg, str) else json.dumps(msg, separators=(",", ":"))
        live = self.connected
        if live:
            await asyncio.gather(*(m.send(text) for m in live), return_exceptions=True)

    async def send_state(self, text, match):
        """Everyone gets the same state, and each player their own ball's
        speeds as well ("you": [vx, vy, standing], for physics.js). Only
        they need those, so the others don't pay for them."""
        live = self.connected
        if not live:
            return
        slot = {t: k for k, t in enumerate(self.match_tokens) if t is not None}
        head = text[:-1]  # the JSON object without its closing brace

        def for_member(m):
            k = slot.get(m.token)
            if k is None:
                return text
            vx, vy, ground = match.motion(k)
            return f'{head},"you":[{vx},{vy},{ground}]}}'
        await asyncio.gather(*(m.send(for_member(m)) for m in live), return_exceptions=True)

    async def broadcast_lobby(self):
        await self.broadcast(self.lobby())

    async def error(self, token, text):
        m = self.members.get(token)
        if m is not None and m.connected:
            await m.send({"type": "error", "message": text})

    # --- messages in --------------------------------------------------------
    async def handle(self, token, msg):
        if token not in self.members:
            return  # removed by the host (or gone), with the connection still open
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
                m.note_network(time.monotonic(), msg)
                await m.send({"type": "pong", "t": msg.get("t")})
            return
        if kind in ("report", "client_error"):
            self.playtest_report(token, kind, msg)
            return
        if kind == "name":
            m = self.members[token]
            old = m.name
            clean, notice = self._name(token, msg.get("name"))
            m.rename(clean)
            if notice:
                await m.send({"type": "notice", "message": notice})
            if clean != old:
                self.note("name", was=old, now=clean)
            await self.broadcast_lobby()
            return
        if kind == "report_player":
            await self.report_player(token, msg)
            return
        if kind == "befriend":
            await self.befriend(token, msg)
            return
        if kind == "play":
            await self.stop_watching(token)
            return
        if kind == "color":
            problem = self.pick_color(token, msg.get("color"))
            # "auto": the browser asking for your saved colour; if it's taken, never mind
            if problem and not msg.get("auto"):
                await self.error(token, problem)
            await self.broadcast_lobby()
            return
        if kind in ("pattern", "look"):
            # "pattern": just the pattern; "look": any of pattern, trail, hat, ko
            problems = [self.pick_look(token, k, msg[k]) for k in cosmetics.KINDS if k in msg]
            problem = next((p for p in problems if p), None)
            # "auto": the browser bringing your saved look; what's locked is left off quietly
            if problem and not msg.get("auto"):
                await self.error(token, problem)
            if not all(problems):
                await self.broadcast_lobby()
            return
        if kind == "own_color":
            problem = self.pick_own_color(token, msg.get("color"))
            if problem and not msg.get("auto"):
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
        if kind == "chat":
            await self.chat_message(token, msg.get("text"))
            return
        if kind == "leave":
            await self.leave(token)
            return
        if kind in ("away", "back"):
            # Off to the lobby during a match (a bot plays for you), and back
            if self.match is not None and token in self.match_tokens:
                k = self.match_tokens.index(token)
                if kind == "away":
                    self.match.stand_in(k)
                else:
                    self.match.release(k)
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
        elif kind == "end_match":
            # The host stops the match now (to change the map, say): back to
            # the lobby, no results, nothing counted
            if self.match is not None and self.ending is None:
                self.ending = self.members[token].name
        elif kind == "lobby":
            if self.match is None:
                self.results = None
                self.votes.clear()
                await self.broadcast_lobby()
        elif kind == "kick":
            target = self.token_of(msg.get("id"))
            if target is not None:
                await self.kick(target)

    async def report_player(self, token, msg):
        """Someone reports a player (moderation.py): {"id": their public id,
        "reason": one of moderation.REASONS, "note": optional words}."""
        m = self.members[token]
        target = self.token_of(msg.get("id"))
        if target is None or target == token:
            await self.error(token, "That player isn't in the room any more.")
            return
        other = self.members[target]
        if other.pid in m.reported:
            await m.send({"type": "notice", "message": f"You've already reported {other.name}."})
            return
        now = time.monotonic()
        if len(m.report_times) == m.report_times.maxlen and now - m.report_times[0] < 60:
            await self.error(token, "You've sent a lot of reports. Try again in a minute.")
            return
        m.report_times.append(now)
        m.reported.add(other.pid)
        moderation.REPORTS.add(moderation.make_report(self.code, m, other, msg.get("reason"),
                                                      msg.get("note"), self.recent))
        await m.send({"type": "notice", "message": f"Thanks. Your report about {other.name} was sent."})

    async def stop_watching(self, token):
        """Someone who came to watch wants to play: in the match now if a
        bot's seat is free (wait_for_seat), else in the next one."""
        m = self.members[token]
        if not m.watching:
            return
        if self.match is None and not self.has_space():
            await self.error(token, "The game is full. You can keep watching.")
            return
        m.watching = False
        self.note("play", who=m.name)
        await self.broadcast_lobby()
        if self.match is not None:
            await self.wait_for_seat(token)
        elif self.results is None:
            self.auto_start(AUTO_START)

    async def befriend(self, token, msg):
        """Someone asks a player in the room to be friends ({"id": their
        public id}). Both need to be signed in. If the other already asked,
        they're friends now (accounts.befriend). The other hears about it
        wherever they are on the server (RoomManager.tell_account)."""
        m = self.members[token]
        target = self.token_of(msg.get("id"))
        if target is None or target == token:
            await self.error(token, "That player isn't in the room any more.")
            return
        other = self.members[target]
        if self.ratings is None:
            await self.error(token, "Friends need sign-in, and it's off on this server.")
            return
        if m.account is None:
            await self.error(token, "Sign in to add friends.")
            return
        if other.account is None:
            await self.error(token, f"{other.name} isn't signed in, so they can't have friends yet.")
            return
        try:
            result = self.ratings.befriend(m.account, other.account)
        except Exception as e:
            metrics.event("error", logging.ERROR, room=self.code, where="befriend", error=repr(e))
            await self.error(token, "Couldn't do that just now. Try again in a moment.")
            return
        self.note("befriend", who=m.name, to=other.name, result=result)
        said = {"friends": f"You and {other.name} are friends now!",
                "sent": f"Friend request sent to {other.name}.",
                "already": f"You've already asked {other.name}, or you're friends.",
                "full": "You have too many friends or requests waiting.",
                "no": "You can't add them."}[result]
        await m.send({"type": "notice", "message": said, "friends": result})
        if result in ("friends", "sent") and self.tell_account is not None:
            await self.tell_account(other.account, {
                "type": "notice", "friends": "request" if result == "sent" else "friends",
                **({"from": m.account} if result == "sent" else {}),  # (so the toast can say yes or no)
                "message": f"{m.name} wants to be friends." if result == "sent"
                else f"You and {m.name} are friends now!"})

    def playtest_report(self, token, kind, msg):
        """A browser says what it saw during a match, or that it hit an error."""
        m = self.members.get(token)
        if m is not None:
            playtest.receive(m, kind, msg, room=self.code, settings=self.settings, results=self.results)

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

    def pick_own_color(self, token, color):
        """A signed-in player picks any colour ("#rrggbb"), or None to go
        back to the palette. Whether they get it depends on who else is
        playing (lobby.own_colors)."""
        m = self.members[token]
        if m.account is None:
            return "Sign in to pick any colour."
        if color is not None and not (isinstance(color, str) and HEX_COLOR.match(color.lower())):
            return "Unknown colour."
        m.own_color = color.lower() if color else None
        return None

    def pick_look(self, token, kind, item):
        """Someone picks a pattern, trail, hat or knockout effect
        (cosmetics.py: a few are for signed-in players). Returns what's
        wrong, or None."""
        problem = cosmetics.problem(kind, item, signed_in=self.members[token].account is not None)
        if problem is None:
            setattr(self.members[token], kind, item)
        return problem

    def pick_team(self, token, team):
        """Someone picks a side in the teams mode (0 or 1), or None for "either"."""
        if team is not None and (type(team) is not int or team not in (0, 1)):
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
        self.note("emote", who=m.name, id=emote)
        await self.broadcast({"type": "emote", "slot": self.match_tokens.index(token), "id": emote})

    async def say(self, text):
        """A line in the chat from the room itself ("Sam joined")."""
        line = {"type": "chat", "system": True, "text": text, "at": int(time.time() * 1000)}
        self.chat.append(line)
        await self.broadcast(line)

    async def chat_message(self, token, text):
        """Someone says something: to everyone in the room (in the lobby and
        during a match), with offensive words starred out (moderation.py).
        A few messages a second at most; past that, they're told to slow down."""
        m = self.members.get(token)
        if m is None or not isinstance(text, str):
            return
        clean, starred = moderation.clean_chat(text)
        if clean is None:
            return
        if not m.chat_bucket.allow():
            await m.send({"type": "notice", "message": "You're chatting too fast. Wait a moment."})
            return
        if starred:
            metrics.event("chat_filtered", logging.INFO, room=self.code, name=m.name)
        self.note("chat", who=m.name, text=clean)
        line = {"type": "chat", "id": m.pid, "name": m.name, "text": clean, "at": int(time.time() * 1000)}
        self.chat.append(line)
        await self.broadcast(line)

    async def kick(self, token):
        """The host removes someone. They can't come back to this room."""
        m = self.members.get(token)
        if m is None or token == self.host:
            return
        self.banned.add(token)
        if m.account is not None:
            self.banned.add(m.account)  # (signed in: on any browser)
        self.note("kick", who=m.name, by=self.members[self.host].name if self.host in self.members else None)
        metrics.event("kick", room=self.code, name=m.name, account=m.account)
        if m.connected:
            await m.send({"type": "error", "message": "The host removed you from this room.",
                          "fatal": True})
        if self.match is not None and token in self.match_tokens:
            self.match.stand_in(self.match_tokens.index(token))
        del self.members[token]
        self.votes.discard(token)
        if token in self.waiting:
            self.waiting.remove(token)
        await self.say(f"{m.name} was removed by the host")
        await self.broadcast_lobby()

    async def leave(self, token):
        """Someone left on purpose (the Leave button): their place goes now,
        not after LEAVE_GRACE. Like a dropped connection otherwise: a bot
        finishes their match, and the host role moves on."""
        m = self.members.pop(token, None)
        if m is None:
            return
        self.note("leave", who=m.name)
        await self.say(f"{m.name} left")
        if self.match is not None and token in self.match_tokens:
            self.match.stand_in(self.match_tokens.index(token))
        self.votes.discard(token)
        if token in self.waiting:
            self.waiting.remove(token)
        if self.host == token:
            live = self.connected
            self.host = live[0].token if live else next(iter(self.members), None)
        if not self.connected:
            self.empty_since = time.monotonic()
        await self.broadcast_lobby()
        await self._maybe_rematch()

    async def _maybe_rematch(self):
        """On the results screen, start again once everyone here has voted."""
        live = {m.token for m in self.connected}
        if self.match is None and self.results is not None and live and live <= self.votes:
            await self.start()

    def update_settings(self, msg):
        """Apply the host's changes. Returns an error message or None."""
        if self.match is not None:
            return "Settings can't change during a match."
        self.settings, problem = lobby.check_settings(self.settings, msg, len(self.players), self.bot_options)
        return problem

    # --- matches ------------------------------------------------------------
    def seats(self):
        """Who would play if the match started now: (member tokens, bot kinds)."""
        return lobby.seats(self.settings, [m.token for m in self.players], self._fill())

    def teams_for(self, humans, n_bots):
        return lobby.teams_for(self.settings["mode"], [self.members[t].team for t in humans], n_bots)

    def colors_for(self, humans, n_bots, teams=None):
        return lobby.colors_for([self.members[t].color for t in humans], n_bots, teams)

    def lineup(self):
        """The seats as they'd be if the match started now, for the lobby."""
        return lobby.lineup(self.settings, self.members, [m.token for m in self.players], self._fill())

    def _fill(self):
        """Quick play rooms: how many players bots make it up to (lobby.QUICK_FILL)."""
        return lobby.QUICK_FILL if self.quick else None

    async def start(self):
        if self.match is not None:
            return
        if self.closing:
            await self.error(self.host, "The server is restarting. Start again in a moment.")
            return
        humans, bots = self.seats()
        fewest = MAPS[self.settings["map"]].players[0]
        if len(humans) + len(bots) < fewest:
            await self.error(self.host, f"Add a bot or invite someone: {MAPS[self.settings['map']].title} "
                                        f"needs at least {fewest} players.")
            return
        teams = self.teams_for(humans, len(bots))
        colors = self.colors_for(humans, len(bots), teams)
        own = lobby.own_colors(colors, [self.members[t].own_color for t in humans] + [None] * len(bots), teams)
        slots = [{"kind": "human", "name": self.members[t].name, "id": self.members[t].pid, "color": c,
                  **self.members[t].look(), "own_color": own[k]}
                 for k, (t, c) in enumerate(zip(humans, colors))]
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
                           gravity=GRAVITY[s["gravity"]], speed=SPEEDS[s.get("speed", "normal")],
                           power_ups=s["power_ups"], power_kinds=s.get("power_kinds"))
        self.match_tokens = humans + [None] * len(bots)
        # Who's signed in, as the match starts (a stand-in bot plays for
        # anyone who drops out; the match still counts for them)
        self.match_accounts = [self.members[t].account for t in humans] + [None] * len(bots)
        self.rated_accounts = list(self.match_accounts)  # (dropping in mid-match isn't rated)
        self.waiting = [m.token for m in self.players if m.token not in humans]
        self.results = None
        self.ending = None
        self.votes.clear()
        await self.broadcast(self.match.describe())
        await self.broadcast_lobby()
        metrics.STATS.matches_started += 1
        metrics.event("match_started", room=self.code, map=s["map"], mode=s["mode"],
                      people=len(humans), bots=len(bots), power_ups=s["power_ups"])
        self.task = asyncio.ensure_future(self.run_match())

    async def run_match(self):
        """Step the match 30 times a second and send everyone the state."""
        match = self.match
        self.encoder = encoder = delta.Encoder()
        loop = asyncio.get_running_loop()
        stats = metrics.STATS
        began = loop.time()
        began_at = time.time()
        next_t = began
        why = "finished"
        match_accounts = self.match_accounts  # (people who drop in are added to it)
        try:
            while not match.finished:
                if self.ending is not None:
                    why = "ended"
                    break
                if self.waiting:
                    await self.drop_in()
                t0 = time.perf_counter()
                events = match.tick()
                state = match.snapshot()
                state["events"] = events
                text = json.dumps(encoder.encode(state), separators=(",", ":"))
                stats.tick(time.perf_counter() - t0)
                await self.send_state(text, match)
                next_t += 1 / TICK_HZ
                delay = next_t - loop.time()
                if delay < -0.25:
                    stats.late_ticks += 1
                    stats.late_at.append(stats.clock())
                    next_t = loop.time()  # fell far behind: don't try to catch up
                await asyncio.sleep(max(0.0, delay))
                if not self.connected:
                    why = "everyone_left"
                    break  # everyone left: stop simulating
            if why != "ended":
                self.results = match.results()
                # For players' match history (profiles.py): which match, and when
                self.results["match_id"] = f"{self.code}-{int(began_at * 1000)}"
                self.results["at"] = int(began_at)
                self.results["slots"] = match.describe()["slots"]
                if match.finished:
                    self._rate(match_accounts)  # (first: it adds the social highlights)
                self._record(match_accounts)
        except asyncio.CancelledError:
            why = "stopped"
            raise
        except Exception as e:
            why = "error"
            self.results = None
            metrics.event("error", logging.ERROR, room=self.code, where="match", error=repr(e),
                          trace=traceback.format_exc())
        finally:
            self.match = None
            self.match_tokens = []
            self.task = None
            self.encoder = None
            stats.matches_finished += 1
            metrics.event("match_ended", room=self.code, why=why, ticks=match.env.steps,
                          seconds=round(loop.time() - began, 1),
                          scores=match.mode.scores())
        self.waiting = []
        if why == "ended":
            ender, self.ending = self.ending, None
            await self.say(f"{ender} ended the match")
        elif self.results is not None:
            await self.broadcast(self.results)
        else:
            await self.broadcast({"type": "error", "message": "Something went wrong in that match. Sorry!"})
        await self.broadcast_lobby()
        if why == "finished":
            self.auto_start(AUTO_NEXT)

    # --- joining a match that's on, and quick-play rooms ---------------------
    async def wait_for_seat(self, token):
        """Someone joined during the match: they take over a bot's seat as
        soon as they can (drop_in), or watch and play in the next match."""
        if token not in self.waiting:
            self.waiting.append(token)
        free = self._bot_seats()
        m = self.members[token]
        if not free:
            await m.send({"type": "notice", "message": "A match is on. You'll play in the next one."})
        elif not self.match.can_drop_in():
            name = self.match.slots[free[0]]["name"]
            await m.send({"type": "notice", "message": f"You'll take over from {name} at the next round."})
        await self.drop_in()

    def _bot_seats(self):
        """Seats in this match played by bots (the last one first)."""
        return [k for k in reversed(range(len(self.match_tokens))) if self.match_tokens[k] is None]

    async def drop_in(self):
        """People waiting take over bots' seats, if the match allows it now."""
        match = self.match
        if match is None or not match.can_drop_in():
            return
        free = self._bot_seats()
        while self.waiting and free:
            token = self.waiting.pop(0)
            m = self.members.get(token)
            if m is None or not m.connected:
                continue
            k = free.pop(0)
            was = match.slots[k]["name"]
            match.take_seat(k, {"name": m.name, "id": m.pid, **m.look()})
            self.match_tokens[k] = token
            self.match_accounts[k] = m.account
            self.note("drop_in", who=m.name, seat=was)
            await self.broadcast({"type": "seat", "slot": k, "info": match.describe_slot(k)})
            await m.send({"type": "notice", "message": f"You're in! You took over from {was}."})
            await self.broadcast_lobby()
        if not free:
            self.waiting = []  # (the rest play in the next match)

    def auto_start(self, delay):
        """Quick-play rooms start their next match by themselves."""
        if not self.quick or self.closing or (self.auto_task is not None and not self.auto_task.done()):
            return

        async def go():
            await asyncio.sleep(delay)
            self.auto_task = None
            if self.match is None and self.players and not self.closing:
                await self.start()
        self.auto_task = asyncio.ensure_future(go())

    def _record(self, accounts):
        """Add the match to each signed-in player's history."""
        if self.recorder is None:
            return
        for slot, account in enumerate(accounts):
            if account is None:
                continue
            tz = next((m.tz for m in self.members.values() if m.account == account), None)
            hour = None if tz is None else int((self.results["at"] // 60 + tz) // 60 % 24)
            try:
                self.recorder(account, profiles.history_entry(self.results, slot, self.results["match_id"],
                                                              self.results["at"], self.results["map"], hour))
            except Exception as e:  # never lose the results over it
                metrics.event("error", logging.ERROR, room=self.code, where="record", error=repr(e))

    def _rating(self, account):
        """A signed-in player's rating badge, or None."""
        if account is None or self.ratings is None:
            return None
        try:
            return self.ratings.rating(account)
        except Exception as e:  # (never keep anyone out over it)
            metrics.event("error", logging.ERROR, room=self.code, where="rating", error=repr(e))
            return None

    def _rate(self, accounts):
        """Rate the match (rating.py): the signed-in people who played it from
        the start. Their changes go in the results (by slot) and their new
        ratings show in the lobby."""
        if self.ratings is None:
            return
        res = self.results
        teams = [s.get("team") for s in res["slots"]]
        players = [{"id": a, "place": res["summaries"][k]["place"], "won": res["summaries"][k]["won"],
                    "team": teams[k] if k < len(teams) else None}
                   for k, a in enumerate(accounts) if a is not None and a == self.rated_accounts[k]]
        if len({p["id"] for p in players}) != len(players):
            return  # (one account in two seats: can't happen, but don't rate it)
        try:
            changes = self.ratings.rate(players)
        except Exception as e:  # never lose the results over it
            metrics.event("error", logging.ERROR, room=self.code, where="rate", error=repr(e))
            return
        if not changes:
            return
        res["ratings"] = {str(k): {x: v for x, v in changes[a].items() if x != "feats"}
                          for k, a in enumerate(accounts) if a in changes}
        # Social highlights (Giant Slayer, Bully, Rival: accounts.rate) join
        # the player's others, for their badges
        for k, a in enumerate(accounts):
            if a in changes and changes[a].get("feats"):
                f = res["summaries"][k].setdefault("feats", {})
                for x, v in changes[a]["feats"].items():
                    f[x] = f.get(x, 0) + v
        for m in self.members.values():
            if m.account in changes:
                m.rating = self._rating(m.account)

    async def stop(self):
        if self.auto_task is not None:
            self.auto_task.cancel()
        if self.task is not None:
            self.task.cancel()

    def listing(self):
        """How the room shows in the game browser. Names are the ones shown
        in the room (already moderated); never anyone's token, nor the
        room's password (only whether it has one)."""
        s = self.settings
        humans, bots = self.seats()
        info = MAPS[s["map"]]
        mode = modes.MODES[s["mode"]]
        host = self.members.get(self.host)
        match = self.match
        return {"room": self.code, "name": lobby.room_title(s, host.name if host else None),
                "locked": bool(s.get("password")), "map": info.title, "map_id": s["map"],
                "mode": mode.title, "mode_id": s["mode"],
                "goal": mode.goal_short(s["first_to"]),
                "people": len(self.players), "bots": len(bots), "most": info.players[1],
                "watching": len(self.connected) - len(self.players),
                "names": [m.name for m in self.players][:limits.MAX_MEMBERS],
                "playing": match is not None,
                "elapsed": round(match.tick_count / TICK_HZ) if match is not None else None,
                "open": self.has_space(),
                "power_ups": bool(s.get("power_ups")), "gravity": s.get("gravity", "normal"),
                "speed": s.get("speed", "normal"),
                "quick": self.quick, "host": host.name if host else None,
                "ping": self.ping()}

    def ping(self):
        """The players' round trip to the server (ms, the middle one of the
        people here, as their browsers last said), or None before anyone's
        said. Everyone plays on this one server, so this is how laggy the
        people in the room are, not how laggy it would be for you."""
        rtts = sorted(m.rtt for m in self.connected if m.rtt is not None)
        return rtts[len(rtts) // 2] if rtts else None

    def has_space(self):
        """Is there room to play here (now or in the next match)?"""
        most = MAPS[self.settings["map"]].players[1]
        return len(self.players) < most and len(self.members) < limits.MAX_MEMBERS


def valid_code(code):
    return (isinstance(code, str) and len(code) == ROOM_CODE_LEN
            and all(c in ROOM_ALPHABET for c in code))


class RoomManager:
    def __init__(self, agents=None, rng=None, recorder=None):
        self.rooms = {}
        self.agents = agents
        self.recorder = recorder   # (see Room)
        self.profile_of = None     # (see Room)
        self.ratings = None        # (see Room)
        self.rng = rng or random.Random()
        self.draining = False      # shutting down: no new rooms or matches

    def create(self, code=None):
        """A new room with a random code, or with `code` (people coming back
        to their room after a server restart)."""
        if self.draining or len(self.rooms) >= limits.MAX_ROOMS:
            raise ServerFull()
        if code is None and self.busy():  # (a room coming back after a restart still can)
            metrics.STATS.refused_busy += 1
            raise ServerFull()
        if code is None:
            for _ in range(1000):
                code = "".join(self.rng.choice(ROOM_ALPHABET) for _ in range(ROOM_CODE_LEN))
                if code not in self.rooms:
                    break
            else:
                raise RuntimeError("no free room codes")
        elif not valid_code(code) or code in self.rooms:
            raise ValueError(f"bad room code {code!r}")
        self.rooms[code] = Room(code, self.agents, self.recorder, self.profile_of)
        self.rooms[code].ratings = self.ratings
        self.rooms[code].tell_account = self.tell_account
        self.rooms[code].busy = self.busy
        metrics.STATS.rooms_created += 1
        metrics.event("room_created", room=code, rooms=len(self.rooms))
        return self.rooms[code]

    async def drain(self, timeout, poll=0.25):
        """Get ready to shut down: no new rooms or matches, tell everyone, and
        wait (up to `timeout` seconds) for the matches being played to end.
        Then tell every room the server is restarting."""
        self.draining = True
        rooms = list(self.rooms.values())
        playing = sum(1 for r in rooms if r.match is not None)
        metrics.event("draining", rooms=len(rooms), matches_running=playing, timeout=timeout)
        for r in rooms:
            r.closing = True
            if r.match is not None:
                await r.broadcast({"type": "notice", "message":
                                   "The server is restarting after this match."})
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end and any(r.match is not None for r in self.rooms.values()):
            await asyncio.sleep(poll)
        cut = [r.code for r in self.rooms.values() if r.match is not None]
        for r in list(self.rooms.values()):
            await r.stop()
            await r.broadcast({"type": "restart",
                               "message": "The server is restarting. Back in a moment…"})
        metrics.event("drained", cut_short=cut)

    def get(self, code):
        return self.rooms.get((code or "").upper())

    def listed(self):
        """Rooms with people in them, the fullest first, for the game browser."""
        rooms = [r for r in self.rooms.values() if r.connected and not r.closing]
        rooms.sort(key=lambda r: (-len(r.connected), r.created))
        return [r.listing() for r in rooms[:LISTED]]

    def browse(self):
        """What the game browser shows: the rooms, how many people are
        playing, and how many rooms there are past the ones listed."""
        live = [r for r in self.rooms.values() if r.connected and not r.closing]
        listed = self.listed()
        return {"rooms": listed,
                "online": sum(len(r.connected) for r in live),
                "more": max(0, len(live) - len(listed))}

    def people(self):
        """Everyone connected, in every room (players and watchers)."""
        return sum(len(r.connected) for r in self.rooms.values())

    def busy(self):
        """Why the server can't take anyone new right now ("full": as many
        people as limits.MAX_PEOPLE; "behind": matches keep falling behind),
        or None."""
        if self.people() >= limits.MAX_PEOPLE:
            return "full"
        stats = metrics.STATS
        now = stats.clock()
        if sum(1 for t in stats.late_at if now - t < limits.BUSY_WINDOW) >= limits.BUSY_LATE:
            return "behind"
        return None

    async def tell_account(self, account, msg):
        """Send a message to everyone connected as this account, in any room."""
        for r in list(self.rooms.values()):
            for m in r.connected:
                if m.account == account:
                    await m.send(msg)

    def where(self, accounts):
        """Where these accounts are playing: {account: room info} for those
        connected in a room (their friends list shows it). A private room
        says so, never its password."""
        out = {}
        for r in self.rooms.values():
            if r.closing:
                continue
            for m in r.connected:
                if m.account in accounts and m.account not in out:
                    host = r.members.get(r.host)
                    out[m.account] = {"room": r.code, "title": lobby.room_title(r.settings, host.name if host else None),
                                      "locked": bool(r.settings.get("password")),
                                      "playing": r.match is not None, "map": r.settings["map"],
                                      "mode": r.settings["mode"]}
        return out

    def quick_play(self, allow_new=lambda: True):
        """Quick play: the open room (no password) with the most people that still has
        space, or a new one with bots that starts by itself. Returns
        (room, whether it's new), or (None, False) if a room is needed and
        allow_new() says no (the per-IP limit). ServerFull if the server
        can't make one, or is busy (it would turn them away anyway)."""
        if self.busy():
            metrics.STATS.refused_busy += 1
            raise ServerFull()
        best = None
        for r in self.rooms.values():
            if not r.settings.get("password") and not r.closing and r.has_space() and (r.connected or r.quick):
                key = (len(r.players), r.quick)
                if best is None or key > best[0]:
                    best = (key, r)
        if best is not None:
            return best[1], False
        if not allow_new():
            return None, False
        room = self.create()
        room.settings = lobby.quick_settings()
        room.quick = True
        return room, True

    async def sweep(self):
        """Drop departed members and expired rooms. Run every few seconds."""
        now = time.monotonic()
        for code, room in list(self.rooms.items()):
            await room.prune(now)
            if room.expired(now):
                await room.stop()
                del self.rooms[code]
                metrics.event("room_closed", room=code, rooms=len(self.rooms),
                              minutes=round((now - room.created) / 60, 1))
