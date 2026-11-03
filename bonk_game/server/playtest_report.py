"""Turn playtest reports into a Markdown write-up (for issue #33).

    python -m bonk_game.server.playtest_report server.log [more.log ...]
    python -m bonk_game.server.playtest_report https://bonk.example.com [--token T]
    fly logs -a my-bonk --no-tail | python -m bonk_game.server.playtest_report -

Reads the server's JSON log lines (any prefix before the "{", as Fly and
Docker add, is skipped) or a running server's /api/playtest, and prints
one row per report, a summary by device, how matches felt, the errors and
a list of things to look at. See playtest.py for what a report holds.
"""
import argparse
import collections
import json
import re
import sys
import urllib.request

# Over these, a report is worth a look
PING_P95 = 150      # ms
JITTER = 30         # ms, average change between pings
LATE_PER_MIN = 6    # states that came more than 100 ms after the last one
BIG_PER_MIN = 3     # own-ball corrections of more than 6 px (rubber-banding)
FPS_LOW = 45
SLOW_PER_MIN = 30   # frames that took more than 50 ms

EVENTS = ("playtest", "client_error", "error", "match_ended", "match_started")


def read_lines(lines):
    """The events we care about, from log lines."""
    out = []
    for line in lines:
        i = line.find("{")
        if i < 0:
            continue
        try:
            rec = json.loads(line[i:])
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("event") in EVENTS:
            out.append(rec)
    return out


def read_url(base, token=None):
    req = urllib.request.Request(base.rstrip("/") + "/api/playtest")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.load(res)["items"]


def device_kind(dev):
    ua = (dev or {}).get("ua", "")
    if re.search(r"iPhone|Android.*Mobile|Mobi", ua):
        kind = "phone"
    elif re.search(r"iPad|Android", ua) or ("Macintosh" in ua and (dev or {}).get("touch")):
        kind = "tablet"
    else:
        kind = "desktop"
    for name, pat in (("Edge", "Edg/"), ("Firefox", "Firefox/|FxiOS"), ("Chrome", "Chrome/|CriOS"),
                      ("Safari", "Safari/")):
        if re.search(pat, ua):
            return kind, name
    return kind, ""


def per_min(r, count):
    secs = r.get("seconds") or 0
    return count * 60 / secs if secs >= 10 else None


def _g(r, section, key, default=None):
    return (r.get(section) or {}).get(key, default)


def problems(r):
    """What looks wrong in one report, in words."""
    out = []
    p95 = _g(r, "ping", "p95")
    if p95 is not None and p95 > PING_P95:
        out.append(f"high ping ({p95:.0f} ms p95)")
    jit = _g(r, "ping", "jitter")
    if jit is not None and jit > JITTER:
        out.append(f"jittery ping (±{jit:.0f} ms)")
    late = per_min(r, _g(r, "states", "late", 0))
    if late is not None and late > LATE_PER_MIN:
        out.append(f"states arriving late ({late:.0f}/min, worst gap {_g(r, 'states', 'max_gap', 0):.0f} ms)")
    if _g(r, "states", "missed", 0):
        out.append(f"{_g(r, 'states', 'missed'):.0f} changes that couldn't be applied")
    big = per_min(r, _g(r, "corrections", "big", 0))
    if big is not None and big > BIG_PER_MIN:
        out.append(f"rubber-banding ({big:.0f} corrections over 6 px a minute)")
    if _g(r, "corrections", "huge", 0):
        out.append(f"{_g(r, 'corrections', 'huge'):.0f} corrections over 20 px "
                   f"(worst {_g(r, 'corrections', 'max', 0):.0f} px)")
    fps = _g(r, "frames", "fps")
    if fps is not None and fps < FPS_LOW:
        out.append(f"low frame rate ({fps:.0f} fps)")
    slow = per_min(r, _g(r, "frames", "slow", 0))
    if slow is not None and slow > SLOW_PER_MIN:
        out.append(f"stutter ({slow:.0f} frames over 50 ms a minute)")
    if r.get("reconnects"):
        out.append(f"lost connection {r['reconnects']:.0f}×")
    if r.get("feel") in ("laggy", "unplayable"):
        out.append(f"felt {r['feel']}")
    return out


def _f(v, fmt="{:.0f}"):
    return "–" if v is None else fmt.format(v)


def _cell(s):
    return str(s).replace("|", "\\|")


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def summarize(records):
    reports = [r for r in records if r.get("event") == "playtest"]
    browser_errors = [r for r in records if r.get("event") == "client_error"]
    server_errors = [r for r in records if r.get("event") == "error"]
    matches = [r for r in records if r.get("event") == "match_ended"]
    lines = ["# Playtest write-up", ""]
    if not reports and not browser_errors and not server_errors:
        return "\n".join(lines + ["No playtest reports found.", ""])
    times = sorted(r["t"] for r in records if r.get("t"))
    people = {r.get("name") for r in reports}
    rooms = {r.get("room") for r in reports}
    lines.append(f"{len(reports)} reports from {len(people)} people in {len(rooms)} rooms"
                 + (f", {times[0]} to {times[-1]}" if times else "") + ".")
    if matches:
        why = collections.Counter(m.get("why") for m in matches)
        lines.append(f"{len(matches)} matches ended: " + ", ".join(f"{n} {k}" for k, n in why.most_common()) + ".")
    lines.append(f"{len(browser_errors)} browser errors, {len(server_errors)} server errors.")
    lines.append("")

    flagged = [(r, problems(r)) for r in reports]
    lines += ["## Things to look at", ""]
    any_flag = False
    for r, probs in flagged:
        if probs:
            any_flag = True
            kind, browser = device_kind(r.get("device"))
            net = _g(r, "device", "net", "")
            who = f"{r.get('name', '?')} ({', '.join(x for x in (kind, browser, net) if x)})"
            lines.append(f"- **{who}**, {r.get('map')} {r.get('mode')}: " + "; ".join(probs))
    if browser_errors:
        any_flag = True
        lines.append(f"- {len(browser_errors)} browser errors (below)")
    if server_errors:
        any_flag = True
        lines.append(f"- {len(server_errors)} server errors (below)")
    if not any_flag:
        lines.append("Nothing over the limits: ping, late states, corrections and frame rate all look fine.")
    lines.append("")

    if reports:
        lines += ["## Reports", "",
                  "| when | who | device | network | ping med / p95 | jitter | late states /min "
                  "| corrections >6 px /min | worst correction | fps | felt | note |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in reports:
            kind, browser = device_kind(r.get("device"))
            late = per_min(r, _g(r, "states", "late", 0))
            big = per_min(r, _g(r, "corrections", "big", 0))
            extra = []
            if r.get("watching"):
                extra.append("watching")
            if r.get("lag"):
                extra.append(f"?lag={r['lag']:.0f}")
            if r.get("predict") is False:
                extra.append("no prediction")
            row = [r.get("t", "")[11:16], r.get("name", "?"),
                   " ".join(x for x in (kind, browser) if x) + (" (" + ", ".join(extra) + ")" if extra else ""),
                   _g(r, "device", "net", "") or "–",
                   f"{_f(_g(r, 'ping', 'med'))} / {_f(_g(r, 'ping', 'p95'))} ms",
                   _f(_g(r, "ping", "jitter"), "±{:.0f} ms"),
                   _f(late, "{:.1f}"), _f(big, "{:.1f}"),
                   _f(_g(r, "corrections", "max"), "{:.0f} px"),
                   _f(_g(r, "frames", "fps")), r.get("feel", "–"), r.get("note", "")]
            lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
        lines.append("")

        lines += ["## By device", "",
                  "| device | reports | ping (median) | corrections >6 px /min (median) | fps (median) |",
                  "|---|---|---|---|---|"]
        by = collections.defaultdict(list)
        for r in reports:
            by[device_kind(r.get("device"))[0]].append(r)
        for kind, rs in sorted(by.items()):
            lines.append(f"| {kind} | {len(rs)} | {_f(_median(_g(r, 'ping', 'med') for r in rs), '{:.0f} ms')} "
                         f"| {_f(_median(per_min(r, _g(r, 'corrections', 'big', 0)) for r in rs), '{:.1f}')} "
                         f"| {_f(_median(_g(r, 'frames', 'fps') for r in rs))} |")
        lines.append("")

        feels = collections.Counter(r.get("feel") for r in reports if r.get("feel"))
        notes = [r for r in reports if r.get("note")]
        lines += ["## How it felt", ""]
        if feels:
            lines.append(", ".join(f"{n} {k}" for k, n in feels.most_common()) + ".")
        else:
            lines.append("Nobody said.")
        for r in notes:
            lines.append(f"- {r.get('name', '?')} ({r.get('map')}): “{r['note']}”")
        lines.append("")

    if browser_errors or server_errors:
        lines += ["## Errors", ""]
        groups = collections.Counter((e.get("message"), e.get("where")) for e in browser_errors)
        for (msg, where), n in groups.most_common():
            lines.append(f"- browser, {n}×: `{msg}`" + (f" at {where}" if where else ""))
        groups = collections.Counter((e.get("where"), e.get("error")) for e in server_errors)
        for (where, err), n in groups.most_common():
            lines.append(f"- server ({where}), {n}×: `{err}`")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write up playtest reports as Markdown.")
    parser.add_argument("sources", nargs="+", help="log files, - for stdin, or a server's URL")
    parser.add_argument("--token", help="BONK_METRICS_TOKEN, for a server's /api/playtest")
    args = parser.parse_args(argv)
    records = []
    for src in args.sources:
        if src.startswith(("http://", "https://")):
            records += read_url(src, args.token)
        elif src == "-":
            records += read_lines(sys.stdin)
        else:
            with open(src, encoding="utf-8", errors="replace") as f:
                records += read_lines(f)
    records.sort(key=lambda r: r.get("t", ""))
    print(summarize(records))


if __name__ == "__main__":
    main()
