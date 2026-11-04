"""Moderation basics (issue #36): a name filter, player reports and the
record that goes with them.

- Names: clean_name() replaces an offensive name with "Player NN" rather
  than refusing to join. It catches common spellings (f4ck, f.u.c.k,
  fuuuck), not everything: the lists are short on purpose.
- Mute: on your own screen only, so it lives in the browser (looks.js).
- Reports: a player reports someone from the lobby or the results screen.
  Each report is logged (event "player_report") with the room, both names,
  their accounts if signed in, and what happened in the room lately (joins,
  names, emotes, kicks). The last REPORTS_KEPT are kept in memory for
  GET /api/reports (same token as /metrics):

      curl -H "Authorization: Bearer $TOKEN" https://<server>/api/reports

The limits, honestly:
- Guests have no account, so a removed guest can come back by clearing
  their browser data (or another browser). Kicks of signed-in players
  stick to their account, on any device, for that room.
- Reports are for whoever runs the server to read; nothing happens to the
  reported player automatically. Bans across the whole server would build
  on accounts (#38).
- Reports are kept in memory, so a restart clears them (the logs keep them).
"""
import collections
import logging
import random
import re
import time

from . import metrics

NAME_LEN = 16
REPORTS_KEPT = 500
REPORTS_PER_MINUTE = 3     # per person
REPORT_NOTE_LEN = 200
REASONS = {"name": "Offensive name", "emotes": "Spamming emotes", "cheating": "Cheating",
           "other": "Something else"}
RECENT_KEPT = 40           # events a room remembers, for reports

# Look-alike characters, so "f4ck" and "$hit" count
_LEET = str.maketrans({"0": "o", "1": "i", "!": "i", "|": "i", "3": "e", "4": "a", "@": "a",
                       "5": "s", "$": "s", "7": "t", "+": "t", "8": "b", "9": "g", "6": "g"})
# Caught anywhere in a name, even run together with other letters
ANYWHERE = (
    "nigger", "nigga", "faggot", "fagot", "retard", "tranny", "wetback", "beaner",
    "fuck", "fuk", "fck", "fvck", "fack", "phuck", "shit", "cunt", "bitch", "whore", "slut", "pussy", "asshole",
    "dickhead", "motherf", "twat", "wanker", "porn", "penis", "vagina", "hitler", "nazi",
    "molest", "pedophil", "paedophil", "killyourself", "siegheil",
)
# Caught as a word on its own ("dick", but not "Dickens"; "rape", but not "grapes")
WORDS = (
    "fag", "fags", "dick", "dicks", "cock", "cocks", "rape", "raped", "kys", "kike", "chink",
    "gook", "coon", "spic", "dyke", "negro", "cum", "jizz", "tits", "boobs", "anal", "sex",
    "nsfw", "ass", "arse", "piss", "trannie", "wank", "pedo", "rapist", "kkk",
)
_SQUEEZE = re.compile(r"(.)\1+")


def _squeeze(s):
    """Letters said more than once in a row, once ("fuuuck" -> "fuck")."""
    return _SQUEEZE.sub(r"\1", s)


# (and squeezed, unless that leaves too little: "kkk" isn't "k")
_ANYWHERE = set(ANYWHERE) | {_squeeze(w) for w in ANYWHERE if len(_squeeze(w)) >= 4}
_WORDS = set(WORDS) | {_squeeze(w) for w in WORDS if len(_squeeze(w)) >= 3}


def offensive(name):
    """Does `name` look offensive? Spaces, dots and look-alike characters
    don't hide a word, and nor does saying a letter more than once."""
    low = str(name or "").lower().translate(_LEET)
    letters = re.sub(r"[^a-z]", "", low)
    for text in (letters, _squeeze(letters)):
        if any(w in text for w in _ANYWHERE):
            return True
    words = re.findall(r"[a-z]+", low)
    if any(w in _WORDS or _squeeze(w) in _WORDS for w in words):
        return True
    # "f u c k" and "d.i.c.k": the name is one word spelt out
    return letters in _WORDS or _squeeze(letters) in _WORDS


def clean_name(name, rng=random):
    """(the name to use, whether it was replaced). Extra spaces go, it's cut
    to NAME_LEN, and an offensive name becomes "Player NN"."""
    name = " ".join(str(name or "").split())[:NAME_LEN]
    if not name:
        return "Player", False
    if offensive(name):
        return f"Player {rng.randint(10, 99)}", True
    return name, False


class Reports:
    """The latest player reports, for GET /api/reports."""

    def __init__(self, kept=REPORTS_KEPT):
        self.items = collections.deque(maxlen=kept)
        self.total = 0

    def add(self, report):
        self.items.append(report)
        self.total += 1
        metrics.event("player_report", logging.WARNING, **report)


REPORTS = Reports()


def make_report(room, reporter, reported, reason, note, recent):
    """A report as it's kept: who, about whom, why, and what happened in
    the room lately. reporter, reported: room.Member."""
    return {
        "at": int(time.time()),
        "room": room,
        "reason": reason if reason in REASONS else "other",
        "note": " ".join(str(note or "").split())[:REPORT_NOTE_LEN],
        "reporter": {"name": reporter.name, "account": reporter.account},
        "reported": {"name": reported.name, "account": reported.account,
                     "names": list(reported.names)},
        "recent": list(recent),
    }
