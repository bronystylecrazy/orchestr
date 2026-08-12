#!/usr/bin/env python3
"""orchestr scorecard — read-only fleet metrics from the tracker's own records.

Run from inside a clone of the target repo (glab infers the project).
Usage: python3 scorecard.py [--days 7]
"""
import argparse
import json
import re
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
    spent = defaultdict(int)           # /spend seconds per producing seat
    overruns = []                      # tickets where spent > 2x estimate
    spend_audit = []                   # /spend values far from server-timestamp truth
    spend_re = re.compile(r"(added|subtracted) (.+?) of time spent")
    dur_re = re.compile(r"(\d+)([dhm])")
    claim_re = re.compile(r"(claim|review-claim|rework-claim):")

    def audit_spends(ref, notes):
        claims = [n for n in notes if not n.get("system") and claim_re.match(n["body"])]
        for n in notes:
            sm = n.get("system") and spend_re.match(n["body"])
            if not sm or sm.group(1) != "added":
                continue
            mins = sum(int(v) * {"d": 480, "h": 60, "m": 1}[u] for v, u in dur_re.findall(sm.group(2)))
            prior = [c for c in claims if ts(c["created_at"]) < ts(n["created_at"])]
            if not prior:
                continue
            truth = (ts(n["created_at"]) - ts(prior[-1]["created_at"])).total_seconds() / 60
            if mins > max(5, truth * 2) or mins < truth * 0.3:
                spend_audit.append(f"{ref} {n['author']['username']} spent {mins}m vs ~{truth:.0f}m real")
    confirmed = defaultdict(int)       # peer-check confirmations per PRODUCER
    refuted = defaultdict(int)         # peer-check refutations per PRODUCER
    checks_done = defaultdict(int)     # peer-checks performed per CHECKER
    tier_moves = 0

    for i in issues:
        notes = api(f"projects/:id/issues/{i['iid']}/notes?per_page=100&sort=asc") or []
        audit_spends(f"#{i['iid']}", notes)
        claims = [n for n in notes if n["body"].startswith("claim:")]
        producer = seat_of(claims[-1]["author"]["username"]) if claims else None
        if i["state"] == "closed" and producer:
            done[producer] += 1
            t0, t1 = ts(claims[-1]["created_at"]), ts(i["closed_at"])
            if t0 and t1 and t1 > t0:
                cycle[producer].append((t1 - t0).total_seconds() / 60)
        st = i.get("time_stats") or {}
        if producer and st.get("total_time_spent"):
            spent[producer] += st["total_time_spent"]
        if st.get("time_estimate") and st.get("total_time_spent", 0) > 2 * st["time_estimate"]:
            overruns.append(f"#{i['iid']} spent {st['total_time_spent']//60}m vs est {st['time_estimate']//60}m")
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
        # MR time: /spend quick-actions leave system notes — attribute per note author
        mr_notes = api(f"projects/:id/merge_requests/{m['iid']}/notes?per_page=100&sort=asc") or []
        audit_spends(f"!{m['iid']}", mr_notes)
        for n in mr_notes:
            if not n.get("system"):
                continue
            sm = spend_re.match(n["body"])
            if not sm:
                continue
            secs = sum(int(v) * {"d": 28800, "h": 3600, "m": 60}[u]
                       for v, u in dur_re.findall(sm.group(2)))
            spent[seat_of(n["author"]["username"])] += secs if sm.group(1) == "added" else -secs

    seats = sorted(set(list(done) + list(rework) + list(confirmed) + list(refuted)
                       + list(merges) + list(checks_done)))
    win = f"last {args.days}d"
    print(f"orchestr scorecard — {win}, generated {now.strftime('%Y-%m-%d %H:%M')}Z")
    print("=" * 72)
    print(f"{'SEAT':<14}{'done':>5}{'peer-ok':>9}{'refuted':>9}{'checks':>8}"
          f"{'rework/MR':>11}{'merges':>8}{'med cycle':>11}{'spent':>8}")
    for s in seats:
        rw = rework.get(s)
        rw_s = f"{statistics.mean(rw):.1f}" if rw else "—"
        cy = cycle.get(s)
        cy_s = humanize(statistics.median(cy)) if cy else "—"
        sp_s = humanize(spent[s] / 60) if spent.get(s) else "—"
        print(f"{s:<14}{done.get(s, 0):>5}{confirmed.get(s, 0):>9}{refuted.get(s, 0):>9}"
              f"{checks_done.get(s, 0):>8}{rw_s:>11}{merges.get(s, 0):>8}{cy_s:>11}{sp_s:>8}")
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
    # --- session ledger (local machine only; written by bin/seat-loop.sh) ---
    import glob
    import os
    led = defaultdict(lambda: {"n": 0, "cost": 0.0, "tin": 0, "tout": 0, "err": 0})
    cutoff = now - timedelta(days=args.days)
    for f in glob.glob(os.path.expanduser("~/.config/orchestr/ledger/*.jsonl")):
        prof = os.path.basename(f)[:-6]
        for line in open(f):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ts(r.get("ts"))
            if not t or t < cutoff:
                continue
            k = f"{r.get('bot', '?')} ({prof})"
            led[k]["n"] += 1
            led[k]["cost"] += r.get("cost_usd") or 0
            led[k]["tin"] += r.get("in") or 0
            led[k]["tout"] += r.get("out") or 0
            led[k]["err"] += 1 if r.get("is_error") else 0
    if led:
        print("-" * 72)
        print(f"{'LEDGER (sessions)':<24}{'runs':>6}{'cost':>9}{'in-tok':>10}{'out-tok':>9}{'errs':>6}")
        tot = {"n": 0, "cost": 0.0}
        for k in sorted(led):
            v = led[k]
            print(f"{k:<24}{v['n']:>6}{'$%.2f' % v['cost']:>9}{v['tin']:>10}{v['tout']:>9}{v['err']:>6}")
            tot["n"] += v["n"]; tot["cost"] += v["cost"]
        print(f"{'total':<24}{tot['n']:>6}{'$%.2f' % tot['cost']:>9}   (API-equivalent; subscription seats bill by plan)")

    # orphans: routed (tier label) but invisible to every queue — no ready-for-agent,
    # no assignee, no open MR. A claim strips the label; a crashed session never restores it.
    mr_refs = " ".join((m.get("description") or "") + m["title"] for m in open_mrs)
    for i in open_issues:
        parked = {"ready-for-human", "needs-info", "wontfix", "needs-triage", "ready-for-agent"}
        if any(l.startswith("tier:") for l in i.get("labels", [])) \
                and not parked & set(i["labels"]) \
                and not i["assignees"] and f"#{i['iid']}" not in mr_refs:
            flags.append(f"ORPHAN #{i['iid']} routed but in no queue (restore ready-for-agent)")

    # stale blocks: labeled `blocked` but every named blocker is closed
    open_iids = {str(i["iid"]) for i in open_issues}
    for i in open_issues:
        if "blocked" not in i.get("labels", []):
            continue
        named = re.findall(r"\d+", " ".join(re.findall(r"[Bb]locked by:?\s*(#\d[\d,\s#]*)", i.get("description") or "")))
        if named and not (set(named) & open_iids):
            flags.append(f"STALE-BLOCK #{i['iid']} blockers all closed (unblock it)")

    flags.extend(f"OVERRUN {o}" for o in overruns)
    flags.extend(f"SPEND? {s}" for s in spend_audit)
    print("FLAGS: " + (" · ".join(flags) if flags else "none"))


if __name__ == "__main__":
    main()
