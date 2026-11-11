"""Accounts: who someone is across visits and devices (issue #38).

Optional. Guests play exactly as before; an account only adds a profile
(name, ball, settings, stats, recent matches: profiles.py) that the server
keeps, so it's the same on every device.

People sign in with Google (auth.py); there are no passwords here. What's
stored, in one SQLite file (BONK_DB):
- users:    an id, Google's id for them ("sub"), their email and name, when
            they joined and were last seen
- sessions: a hash of each sign-in's cookie, whose account it is, when it
            ends (SESSION_DAYS). The cookie itself is never stored.
- profiles: each account's profile, as JSON
- ratings:  each account's rating (rating.py), once they've played a rated
            match: the rating, matches, wins, their best, when last rated
- rivals:   how many rated matches each pair of accounts has played
            together (for the Rival badge)
- friends:  pairs of friends (a < b), and friend_requests: who asked whom
            (a request back makes them friends)

Everything goes through Accounts, so moving to another database later only
changes this file. The calls are quick (one small row each), so they run on
the event loop.
"""
import hashlib
import json
import secrets
import sqlite3
import time

from bonk_game.server import moderation, profiles, rating

SESSION_DAYS = 90
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    google_sub TEXT UNIQUE NOT NULL,
    email      TEXT NOT NULL DEFAULT '',
    name       TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    seen_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ratings (
    user_id    TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    rating     REAL NOT NULL,
    games      INTEGER NOT NULL,
    wins       INTEGER NOT NULL,
    peak       REAL NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ratings_rank ON ratings(rating DESC);
CREATE TABLE IF NOT EXISTS friends (
    a     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    b     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    since INTEGER NOT NULL,
    PRIMARY KEY (a, b)
);
CREATE INDEX IF NOT EXISTS friends_b ON friends(b);
CREATE TABLE IF NOT EXISTS friend_requests (
    from_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    at      INTEGER NOT NULL,
    PRIMARY KEY (from_id, to_id)
);
CREATE INDEX IF NOT EXISTS friend_requests_to ON friend_requests(to_id);
CREATE TABLE IF NOT EXISTS rivals (
    a       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    b       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    matches INTEGER NOT NULL,
    PRIMARY KEY (a, b)
);
"""
# What a browser may change in its account's profile. Stats and history are
# the server's: it records each match an account plays (record()).
MAX_FRIENDS = 200    # friends an account can have
MAX_REQUESTS = 50    # friend requests it can have waiting on other people
EDITABLE = ("name", "color", "own_color", "pattern", "trail", "hat", "ko", "muted", "prefs")


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Accounts:
    def __init__(self, path, clock=time.time):
        """path: the SQLite file (":memory:" for tests)."""
        self.path = path
        self.clock = clock
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)

    def _now(self):
        return int(self.clock())

    # --- users --------------------------------------------------------------
    def sign_in(self, google_sub, email="", name=""):
        """The account for this Google user, made on their first sign-in.
        Returns (user, new)."""
        now = self._now()
        row = self.db.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()
        if row is not None:
            self.db.execute("UPDATE users SET email = ?, name = ?, seen_at = ? WHERE id = ?",
                            (email, name, now, row["id"]))
            return self.user(row["id"]), False
        uid = "u" + secrets.token_hex(8)
        profile = profiles.empty("acct-" + secrets.token_hex(8))
        profile["name"] = " ".join(name.split())[:16]
        if moderation.offensive(profile["name"]):
            profile["name"] = ""
        with self.db:
            self.db.execute("BEGIN")
            self.db.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
                            (uid, google_sub, email, name, now, now))
            self.db.execute("INSERT INTO profiles VALUES (?, ?)", (uid, json.dumps(profile)))
        return self.user(uid), True

    def user(self, uid):
        row = self.db.execute("SELECT id, email, name, created_at FROM users WHERE id = ?", (uid,)).fetchone()
        return dict(row) if row else None

    def delete(self, uid):
        """Delete an account: its profile and sign-ins go with it."""
        self.db.execute("DELETE FROM users WHERE id = ?", (uid,))

    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # --- sessions -------------------------------------------------------------
    def new_session(self, uid):
        """A new sign-in for `uid`: returns the cookie value."""
        token = secrets.token_urlsafe(32)
        self.db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                        (_hash(token), uid, self._now() + SESSION_DAYS * 86400))
        return token

    def session_user(self, token):
        """The account a cookie belongs to, or None (unknown or expired)."""
        if not token or len(token) > 100:
            return None
        row = self.db.execute("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
                              (_hash(token),)).fetchone()
        if row is None:
            return None
        if row["expires_at"] < self._now():
            self.end_session(token)
            return None
        return self.user(row["user_id"])

    def end_session(self, token):
        if token:
            self.db.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))

    def sweep(self):
        """Forget expired sign-ins."""
        self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (self._now(),))

    # --- profiles -------------------------------------------------------------
    def profile(self, uid):
        row = self.db.execute("SELECT data FROM profiles WHERE user_id = ?", (uid,)).fetchone()
        if row is None:
            return None
        return profiles.validate(json.loads(row["data"])) or profiles.empty("acct-" + uid)

    def _save(self, uid, p):
        self.db.execute("UPDATE profiles SET data = ? WHERE user_id = ?", (json.dumps(p), uid))
        return p

    def update(self, uid, changes):
        """Change what a browser may change (EDITABLE); the rest is ignored."""
        p = self.profile(uid)
        if p is None or not isinstance(changes, dict):
            return p
        edits = {k: changes[k] for k in EDITABLE if k in changes}
        checked = profiles.validate({**p, **edits})
        if checked is None:
            return p
        return self._save(uid, {**p, **{k: checked[k] for k in edits}})

    def merge(self, uid, other):
        """Add a browser's profile to the account (on first sign-in there). The
        same one twice counts once. A brand-new account takes the browser's
        name, ball and settings too."""
        p = self.profile(uid)
        b = profiles.validate(other)
        if p is None or b is None:
            return p
        fresh = p["stats"]["matches"] == 0 and not p["merged"]
        out = profiles.merge(p, b)
        if fresh:
            out = {**out, **{k: b[k] for k in EDITABLE if b[k] not in ("", None, {})}}
        return self._save(uid, out)

    def record(self, uid, entry):
        """One match the account played (profiles.history_entry)."""
        p = self.profile(uid)
        if p is None:
            return None
        return self._save(uid, profiles.record(p, entry))

    # --- ratings (rating.py) ----------------------------------------------------
    def _rating_row(self, uid):
        row = self.db.execute("SELECT rating, games, wins, peak FROM ratings WHERE user_id = ?", (uid,)).fetchone()
        return dict(row) if row else None

    def rating(self, uid):
        """An account's rating badge (rating.badge), with its place on the
        leaderboard ("rank": None until it's placed)."""
        row = self._rating_row(uid)
        out = rating.badge(row)
        out["rank"] = None
        if row is not None and row["games"] >= rating.PLACEMENT:
            out["rank"] = 1 + self.db.execute(
                "SELECT COUNT(*) FROM ratings WHERE games >= ? AND rating > ?",
                (rating.PLACEMENT, row["rating"])).fetchone()[0]
        return out

    def rate(self, players):
        """Rate a match. players: [{"id": account, "place", "team", "won"}],
        signed-in players only. Returns {account: {"before", "after", "change",
        **badge}} for each, or {} when fewer than two of them played."""
        if len(players) < 2:
            return {}
        now = self._now()
        rows = {p["id"]: self._rating_row(p["id"]) or
                {"rating": rating.START, "games": 0, "wins": 0, "peak": rating.START} for p in players}
        changes = rating.update([{**p, "rating": rows[p["id"]]["rating"], "games": rows[p["id"]]["games"]}
                                 for p in players])
        feats = rating.social_feats([{**p, "rating": rows[p["id"]]["rating"]} for p in players])
        out = {}
        with self.db:
            self.db.execute("BEGIN")
            for p in players:
                row = rows[p["id"]]
                new = {"rating": row["rating"] + changes[p["id"]], "games": row["games"] + 1,
                       "wins": row["wins"] + bool(p.get("won"))}
                new["peak"] = max(row["peak"], new["rating"]) if row["games"] else new["rating"]
                self.db.execute("INSERT OR REPLACE INTO ratings VALUES (?, ?, ?, ?, ?, ?)",
                                (p["id"], new["rating"], new["games"], new["wins"], new["peak"], now))
                out[p["id"]] = {**rating.badge(new), "before": round(row["rating"]),
                                "change": round(new["rating"]) - round(row["rating"]),
                                "feats": feats[p["id"]]}
            # Rivals: each pair's matches together; the RIVAL_MATCHES-th makes them rivals
            ids = sorted(p["id"] for p in players)
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    self.db.execute("INSERT INTO rivals VALUES (?, ?, 1) ON CONFLICT(a, b) "
                                    "DO UPDATE SET matches = matches + 1", (a, b))
                    n = self.db.execute("SELECT matches FROM rivals WHERE a = ? AND b = ?", (a, b)).fetchone()[0]
                    if n == rating.RIVAL_MATCHES:
                        for x in (a, b):
                            out[x]["feats"]["rival"] = out[x]["feats"].get("rival", 0) + 1
        return out

    def leaderboard(self, limit=100):
        """The best placed players: [{rank, id, name, ball, **badge}], and how
        many are placed. id is the profile's id (never the account's)."""
        rows = self.db.execute(
            "SELECT r.user_id, r.rating, r.games, r.wins, r.peak, p.data FROM ratings r "
            "JOIN profiles p ON p.user_id = r.user_id WHERE r.games >= ? "
            "ORDER BY r.rating DESC, r.games DESC, r.user_id LIMIT ?", (rating.PLACEMENT, limit)).fetchall()
        total = self.db.execute("SELECT COUNT(*) FROM ratings WHERE games >= ?",
                                (rating.PLACEMENT,)).fetchone()[0]
        out, rank, last = [], 0, None
        for k, row in enumerate(rows):
            if last is None or row["rating"] < last:  # (equal ratings share a place)
                rank, last = k + 1, row["rating"]
            p = profiles.validate(json.loads(row["data"])) or profiles.empty("acct-" + row["user_id"])
            out.append({"rank": rank, "you": False, "account": row["user_id"], "name": p["name"] or "Player",
                        "ball": {k2: p[k2] for k2 in ("color", "own_color", "pattern", "hat")},
                        **rating.badge(dict(row))})
        return out, total

    # --- friends ------------------------------------------------------------
    def are_friends(self, a, b):
        a, b = sorted((a, b))
        return self.db.execute("SELECT 1 FROM friends WHERE a = ? AND b = ?", (a, b)).fetchone() is not None

    def _count_friends(self, uid):
        return self.db.execute("SELECT COUNT(*) FROM friends WHERE a = ? OR b = ?", (uid, uid)).fetchone()[0]

    def befriend(self, me, other):
        """`me` asks `other` to be friends. If `other` already asked, they're
        friends now. Returns "friends", "sent", "already" (friends, or asked
        already), "full" (one of them has MAX_FRIENDS, or `me` has
        MAX_REQUESTS waiting) or "no" (yourself, or no such account)."""
        if me == other or self.user(other) is None or self.user(me) is None:
            return "no"
        if self.are_friends(me, other):
            return "already"
        asked = self.db.execute("SELECT 1 FROM friend_requests WHERE from_id = ? AND to_id = ?",
                                (other, me)).fetchone()
        if asked:
            if max(self._count_friends(me), self._count_friends(other)) >= MAX_FRIENDS:
                return "full"
            a, b = sorted((me, other))
            with self.db:
                self.db.execute("BEGIN")
                self.db.execute("INSERT OR IGNORE INTO friends VALUES (?, ?, ?)", (a, b, self._now()))
                self.db.execute("DELETE FROM friend_requests WHERE (from_id = ? AND to_id = ?) "
                                "OR (from_id = ? AND to_id = ?)", (me, other, other, me))
            return "friends"
        if self.db.execute("SELECT 1 FROM friend_requests WHERE from_id = ? AND to_id = ?",
                           (me, other)).fetchone():
            return "already"
        waiting = self.db.execute("SELECT COUNT(*) FROM friend_requests WHERE from_id = ?", (me,)).fetchone()[0]
        if waiting >= MAX_REQUESTS or self._count_friends(me) >= MAX_FRIENDS:
            return "full"
        self.db.execute("INSERT INTO friend_requests VALUES (?, ?, ?)", (me, other, self._now()))
        return "sent"

    def unfriend(self, me, other):
        """No longer friends, or a request either way turned down / taken back."""
        a, b = sorted((me, other))
        with self.db:
            self.db.execute("BEGIN")
            self.db.execute("DELETE FROM friends WHERE a = ? AND b = ?", (a, b))
            self.db.execute("DELETE FROM friend_requests WHERE (from_id = ? AND to_id = ?) "
                            "OR (from_id = ? AND to_id = ?)", (me, other, other, me))

    def _people(self, rows):
        out = []
        for row in rows:
            p = profiles.validate(json.loads(row["data"])) or profiles.empty("acct-" + row["id"])
            out.append({"id": row["id"], "name": p["name"] or "Player",
                        "ball": {k: p[k] for k in ("color", "own_color", "pattern", "hat")}})
        return out

    def friends(self, uid):
        """{"friends": [...], "incoming": [...], "outgoing": [...]}: each
        {id, name, ball}, friends by name, requests newest first."""
        friends = self.db.execute(
            "SELECT u.id, p.data FROM friends f JOIN users u ON u.id = CASE WHEN f.a = ? THEN f.b ELSE f.a END "
            "JOIN profiles p ON p.user_id = u.id WHERE f.a = ? OR f.b = ?", (uid, uid, uid)).fetchall()
        incoming = self.db.execute(
            "SELECT r.from_id AS id, p.data FROM friend_requests r JOIN profiles p ON p.user_id = r.from_id "
            "WHERE r.to_id = ? ORDER BY r.at DESC", (uid,)).fetchall()
        outgoing = self.db.execute(
            "SELECT r.to_id AS id, p.data FROM friend_requests r JOIN profiles p ON p.user_id = r.to_id "
            "WHERE r.from_id = ? ORDER BY r.at DESC", (uid,)).fetchall()
        return {"friends": sorted(self._people(friends), key=lambda f: f["name"].lower()),
                "incoming": self._people(incoming), "outgoing": self._people(outgoing)}
