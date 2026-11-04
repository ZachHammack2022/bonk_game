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

Everything goes through Accounts, so moving to another database later only
changes this file. The calls are quick (one small row each), so they run on
the event loop.
"""
import hashlib
import json
import secrets
import sqlite3
import time

from bonk_game.server import profiles

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
"""
# What a browser may change in its account's profile. Stats and history are
# the server's: it records each match an account plays (record()).
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
        """Add a browser's profile (or a profile file) to the account. The
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
