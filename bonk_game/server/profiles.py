"""Player profiles: name, ball, settings, lifetime stats and recent matches.

Browsers keep their profile themselves for now (static/profile.js has the
format). This is the same thing on the server, for when accounts (#38) store
profiles: validate() an uploaded browser profile, merge() it into the
account's, and record() each match the account plays. The rules here and in
profile.js must agree; tests/test_profiles.py checks they do.

Each match's results carry a "summaries" list (match.py): one entry per
slot with how that player did, ready for record() after adding the match's
id, time, mode and map (history_entry).
"""
import math
import re

FORMAT = "bonk-profile"
VERSION = 1
HISTORY = 50
COUNTS = ("matches", "wins", "kos", "falls", "deaths", "pickups")
ENTRY_COUNTS = ("place", "of", "kos", "falls", "deaths", "pickups", "players", "people")
MAX = 10 ** 9
TIME = 10 ** 11  # seconds since 1970: plenty


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _int(v, lo=0, hi=MAX):
    return max(lo, min(hi, int(v))) if _finite(v) else lo


def _num(v):
    if not _finite(v):
        return 0
    # Same as JavaScript's Math.round(v * 10) / 10 (halves round up)
    r = math.floor(v * 10 + 0.5) / 10
    r = max(0, min(MAX, r))
    return int(r) if float(r).is_integer() else r


def _text(v, n):
    return v[:n] if isinstance(v, str) else ""


def _key(v):
    return isinstance(v, str) and 0 < len(v) <= 24 and all(c.isascii() and (c.islower() or c.isdigit() or c in "_-")
                                                          for c in v)


def empty(id_):
    return {"format": FORMAT, "v": VERSION, "id": id_, "merged": [],
            "name": "", "color": None, "own_color": None, "pattern": "plain", "muted": False, "prefs": {},
            "stats": {"matches": 0, "wins": 0, "kos": 0, "falls": 0, "deaths": 0, "pickups": 0,
                      "best_hit": 0, "awards": {}, "modes": {}, "maps": {}, "first_at": None, "last_at": None},
            "history": []}


def _clean_tally(t):
    if not isinstance(t, dict):
        return {}
    return {k: {"matches": _int(t[k].get("matches")), "wins": _int(t[k].get("wins"))}
            for k in sorted(t)[:50] if _key(k) and isinstance(t[k], dict)}


def _clean_entry(e):
    if not isinstance(e, dict) or not _text(e.get("id"), 40):
        return None
    out = {"id": _text(e["id"], 40), "at": _int(e.get("at"), 0, TIME),
           "mode": e["mode"] if _key(e.get("mode")) else "?",
           "map": e["map"] if _key(e.get("map")) else "?",
           "won": e.get("won") is True, "score": _num(e.get("score"))}
    for k in ENTRY_COUNTS:
        out[k] = _int(e.get(k), 0, 1000)
    out["best_hit"] = _num(e.get("best_hit"))
    out["awards"] = [a for a in e.get("awards", []) if _key(a)][:10] if isinstance(e.get("awards"), list) else []
    return out


def validate(p):
    """Any object (an uploaded file) as a valid profile, or None. Settings
    ("prefs") are kept as they are: only the browser reads them."""
    if not isinstance(p, dict) or p.get("format") != FORMAT or not _text(p.get("id"), 40):
        return None
    out = empty(_text(p["id"], 40))
    merged = p.get("merged")
    out["merged"] = [x for x in merged if isinstance(x, str) and x and len(x) <= 40][:100] \
        if isinstance(merged, list) else []
    out["name"] = _text(p.get("name"), 16)
    c = p.get("color")
    out["color"] = c if isinstance(c, int) and not isinstance(c, bool) and 0 <= c < 10 else None
    oc = p.get("own_color")
    out["own_color"] = oc if isinstance(oc, str) and re.fullmatch(r"#[0-9a-f]{6}", oc) else None
    out["pattern"] = _text(p.get("pattern"), 16) or "plain"
    out["muted"] = p.get("muted") is True
    out["prefs"] = p["prefs"] if isinstance(p.get("prefs"), dict) else {}
    s = p.get("stats") if isinstance(p.get("stats"), dict) else {}
    st = out["stats"]
    for k in COUNTS:
        st[k] = _int(s.get(k))
    st["best_hit"] = _num(s.get("best_hit"))
    aw = s.get("awards")
    st["awards"] = {k: _int(aw[k]) for k in sorted(aw)[:20] if _key(k)} if isinstance(aw, dict) else {}
    st["modes"] = _clean_tally(s.get("modes"))
    st["maps"] = _clean_tally(s.get("maps"))
    st["first_at"] = _int(s["first_at"], 0, TIME) if _finite(s.get("first_at")) else None
    st["last_at"] = _int(s["last_at"], 0, TIME) if _finite(s.get("last_at")) else None
    seen, history = set(), []
    for e in p.get("history") if isinstance(p.get("history"), list) else []:
        e = _clean_entry(e)
        if e and e["id"] not in seen:
            seen.add(e["id"])
            history.append(e)
    out["history"] = history[:HISTORY]
    return out


def _tally(t, k, won):
    cur = t.get(k, {"matches": 0, "wins": 0})
    return {**t, k: {"matches": cur["matches"] + 1, "wins": cur["wins"] + (1 if won else 0)}}


def record(p, entry):
    """The profile after one more match; the same match twice counts once."""
    e = _clean_entry(entry)
    if e is None or any(h["id"] == e["id"] for h in p["history"]):
        return p
    s = p["stats"]
    awards = dict(s["awards"])
    for a in e["awards"]:
        awards[a] = awards.get(a, 0) + 1
    stats = {**s,
             "matches": s["matches"] + 1, "wins": s["wins"] + (1 if e["won"] else 0),
             "kos": s["kos"] + e["kos"], "falls": s["falls"] + e["falls"],
             "deaths": s["deaths"] + e["deaths"], "pickups": s["pickups"] + e["pickups"],
             "best_hit": max(s["best_hit"], e["best_hit"]), "awards": awards,
             "modes": _tally(s["modes"], e["mode"], e["won"]), "maps": _tally(s["maps"], e["map"], e["won"]),
             "first_at": e["at"] if s["first_at"] is None else min(s["first_at"], e["at"]),
             "last_at": max(s["last_at"] or 0, e["at"])}
    return {**p, "stats": stats, "history": [e, *p["history"]][:HISTORY]}


def _add_tallies(a, b):
    out = dict(a)
    for k, v in b.items():
        x = out.get(k, {"matches": 0, "wins": 0})
        out[k] = {"matches": x["matches"] + v["matches"], "wins": x["wins"] + v["wins"]}
    return out


def merge(a, b):
    """Two profiles as one: totals add up, recent matches interleave, `a`
    keeps its name, ball and settings. The same profile twice counts once."""
    if a["id"] == b["id"]:
        return dict(b) if b["stats"]["matches"] > a["stats"]["matches"] else a
    if b["id"] in a["merged"]:
        return a
    s, t = a["stats"], b["stats"]
    stats = {**s, "best_hit": max(s["best_hit"], t["best_hit"])}
    for k in COUNTS:
        stats[k] = s[k] + t[k]
    stats["awards"] = dict(s["awards"])
    for k, v in t["awards"].items():
        stats["awards"][k] = stats["awards"].get(k, 0) + v
    stats["modes"] = _add_tallies(s["modes"], t["modes"])
    stats["maps"] = _add_tallies(s["maps"], t["maps"])
    firsts = [x for x in (s["first_at"], t["first_at"]) if x is not None]
    stats["first_at"] = min(firsts) if firsts else None
    lasts = [x for x in (s["last_at"], t["last_at"]) if x is not None]
    stats["last_at"] = max(lasts) if lasts else None
    seen, history = set(), []
    for e in a["history"] + b["history"]:
        if e["id"] not in seen:
            seen.add(e["id"])
            history.append(e)
    history.sort(key=lambda e: (-e["at"], e["id"]))
    merged = list(dict.fromkeys([*a["merged"], b["id"], *b["merged"]]))
    merged = [x for x in merged if x != a["id"]][:100]
    return {**a, "merged": merged, "stats": stats, "history": history[:HISTORY]}


def history_entry(results, slot, match_id, at, map_name):
    """One player's history entry from a match's results (match.py)."""
    summary = results["summaries"][slot]
    slots = results.get("slots") or []
    return {"id": match_id, "at": at, "mode": results["mode"], "map": map_name, **summary,
            "players": len(slots), "people": sum(1 for s in slots if s.get("kind") == "human")}
