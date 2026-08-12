#!/usr/bin/env python3
"""orchestr scorecard — read-only fleet metrics from the tracker's own records.

Run from inside a clone of the target repo (glab infers the project).
Usage: python3 scorecard.py [--days 7]
"""
import argparse
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

TIERS = ["tier:frontier", "tier:standard", "tier:mechanical"]


def api(path):
    r = subprocess.run(["glab", "api", path], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def ts(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def age_h(s, now):
    t = ts(s)
    return (now - t).total_seconds() / 3600 if t else 0


def humanize(minutes):
    if minutes is None:
        return "—"
    if minutes < 90:
        return f"{minutes:.0f} min"
    if minutes < 48 * 60:
        return f"{minutes / 60:.1f} h"
    return f"{minutes / (24 * 60):.1f} d"


def seat_of(username):
    return username if username.startswith("bot-") else "human"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    issues = api(f"projects/:id/issues?updated_after={since}&state=all&per_page=100") or []
    mrs = api(f"projects/:id/merge_requests?updated_after={since}&state=all&per_page=100") or []
    open_issues = api("projects/:id/issues?state=opened&per_page=100") or []
    open_mrs = api("projects/:id/merge_requests?state=opened&per_page=100") or []

    done = defaultdict(int)            # closed issues per producing seat
    cycle = defaultdict(list)          # claim -> close, minutes
    confirmed = defaultdict(int)       # peer-check confirmations per PRODUCER
    refuted = defaultdict(int)         # peer-check refutations per PRODUCER
    checks_done = defaultdict(int)     # peer-checks performed per CHECKER
    tier_moves = 0

    for i in issues:
        notes = api(f"projects/:id/issues/{i['iid']}/notes?per_page=100&sort=asc") or []
        claims = [n for n in notes if n["body"].startswith("claim:")]
        producer = seat_of(claims[-1]["author"]["username"]) if claims else None
        if i["state"] == "closed" and producer:
            done[producer] += 1
            t0, t1 = ts(claims[-1]["created_at"]), ts(i["closed_at"])
            if t0 and t1 and t1 > t0:
                cycle[producer].append((t1 - t0).total_seconds() / 60)
        for n in notes:
            body = n["body"]
            checker = seat_of(n["author"]["username"])
            if body.startswith("peer-check: confirmed") and producer:
                confirmed[producer] += 1
                checks_done[checker] += 1
            elif body.startswith("peer-check: refuted") and producer:
                refuted[producer] += 1
                checks_done[checker] += 1
        events = api(f"projects/:id/issues/{i['iid']}/resource_label_events?per_page=100") or []
        tier_adds = [e for e in events if e.get("action") == "add"
                     and (e.get("label") or {}).get("name") in TIERS]
        if len(tier_adds) > 1:
            tier_moves += len(tier_adds) - 1

    rework = defaultdict(list)         # changes-requested rounds per MR author
    merges = defaultdict(int)          # verified merges per reviewer seat
    for m in mrs:
        author = seat_of(m["author"]["username"])
        events = api(f"projects/:id/merge_requests/{m['iid']}/resource_label_events?per_page=100") or []
        rounds = sum(1 for e in events if e.get("action") == "add"
                     and (e.get("label") or {}).get("name") == "changes-requested")
        rework[author].append(rounds)
        if m["state"] == "merged" and m.get("merge_user"):
            merges[seat_of(m["merge_user"]["username"])] += 1

    seats = sorted(set(list(done) + list(rework) + list(confirmed) + list(refuted)
                       + list(merges) + list(checks_done)))
    win = f"last {args.days}d"
    print(f"orchestr scorecard — {win}, generated {now.strftime('%Y-%m-%d %H:%M')}Z")
    print("=" * 72)
    print(f"{'SEAT':<14}{'done':>5}{'peer-ok':>9}{'refuted':>9}{'checks':>8}"
          f"{'rework/MR':>11}{'merges':>8}{'med cycle':>11}")
    for s in seats:
        rw = rework.get(s)
        rw_s = f"{statistics.mean(rw):.1f}" if rw else "—"
        cy = cycle.get(s)
        cy_s = humanize(statistics.median(cy)) if cy else "—"
        print(f"{s:<14}{done.get(s, 0):>5}{confirmed.get(s, 0):>9}{refuted.get(s, 0):>9}"
              f"{checks_done.get(s, 0):>8}{rw_s:>11}{merges.get(s, 0):>8}{cy_s:>11}")
    if tier_moves:
        print(f"tier escalations/moves in window: {tier_moves}")

    print("-" * 72)
    print(f"{'QUEUE':<22}{'depth':>6}{'oldest':>9}")

    def queue(name, items, key=lambda x: x["created_at"]):
        oldest = humanize(max((age_h(key(x), now) for x in items), default=0) * 60) if items else "—"
        print(f"{name:<22}{len(items):>6}{oldest:>9}")
        return items

    def has(x, label):
        return label in x.get("labels", [])

    ready = [i for i in open_issues if has(i, "ready-for-agent") and not i["assignees"]]
    for t in TIERS:
        queue(f"ready {t.split(':')[1]}", [i for i in ready if has(i, t)])
    queue("peer-check", [i for i in open_issues if has(i, "needs-peer-check")])
    queue("triage inbox", [i for i in open_issues if has(i, "needs-triage")])
    rev = [m for m in open_mrs
           if any(has(m, l) for l in ("review:frontier", "review:light"))
           and not has(m, "changes-requested")]
    queue("reviews", rev)
    queue("rework (changes-req)", [m for m in open_mrs if has(m, "changes-requested")])

    print("-" * 72)
    flags = []
    for m in rev:
        if age_h(m["created_at"], now) > 24:
            flags.append(f"!{m['iid']} awaiting review {age_h(m['created_at'], now):.0f}h")
    for i in open_issues:
        if has(i, "needs-peer-check") and age_h(i["updated_at"], now) > 24:
            flags.append(f"#{i['iid']} needs-peer-check stuck {age_h(i['updated_at'], now):.0f}h")
        if has(i, "ready-for-agent") and not i["assignees"] and age_h(i["created_at"], now) > 48:
            flags.append(f"#{i['iid']} ready untouched {age_h(i['created_at'], now) / 24:.0f}d")
        if i["assignees"] and has(i, "ready-for-agent"):
            # quiet = no notes since the claim; updated_at lies (any label touch resets it)
            inotes = api(f"projects/:id/issues/{i['iid']}/notes?per_page=100&sort=asc") or []
            claim_times = [ts(n["created_at"]) for n in inotes if n["body"].startswith("claim:")]
            if claim_times:
                last_note = max(ts(n["created_at"]) for n in inotes)
                quiet_h = (now - max(claim_times[-1], last_note)).total_seconds() / 3600
                if quiet_h > 24:
                    flags.append(f"#{i['iid']} claimed but quiet {quiet_h:.0f}h")
    print("FLAGS: " + (" · ".join(flags) if flags else "none"))


if __name__ == "__main__":
    main()
