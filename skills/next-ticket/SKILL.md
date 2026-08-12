---
name: next-ticket
description: Use when an agent seat is idle and should pull work from the issue tracker — at session start, after finishing a ticket, or when told to pick up the next ticket.
---

# Next Ticket

Pull-based dispatch: pick → claim → work → hand off. One invocation works one item start to finish; when it ends, the seat is idle again and may re-invoke.

## 1. Identify your seat

- `glab api user` — the username you are authenticated as (your bot identity, e.g. `bot-glm`).
- Read the repo's `docs/agents/model-routing.md`: the **Seats** table maps your identity to a **tier cap**. You may take work at your cap and below — a mechanical seat takes only `tier:mechanical`; a frontier seat may take anything.
- If the doc is missing, run orchestr:init before anything else.

## 2. Pick

**`directed-only` mode** (the skill was invoked with that argument): work **only** queues 0 and 0.5 — your own `changes-requested` MRs and work a human assigned to you by name. If both are empty, stop with "no directed work". Skip everything below.

Every seat checks queue 0 first. Then standard and frontier seats continue at
queue 1; mechanical seats skip to queue 4.

0. **(all seats) Rework — your own MRs come before any new work** — `glab mr list --label changes-requested -F json`, keep only MRs authored by your bot user; skip any whose comments hold a `rework-claim:` from another instance less than 24 hours old. Claim yours first — `glab mr note <iid> --message "rework-claim: $INSTANCE $(date -u +%FT%TZ)"`, re-read, back off if an earlier fresh claim from another instance exists (sibling instances share your bot user — the claim, not authorship, decides whose rework this is). Then: fresh worktree from the remote branch (`git worktree add <path> origin/<branch>`), address every **`(blocking)`** finding (reply to each; non-blocking findings are yours to take or decline — reply either way), push, remove the label (`glab mr update <iid> --unlabel changes-requested`) to hand it back to the review queue, remove the worktree, and clock it — `glab mr note <iid> --message "/spend <minutes>m"` as its own note, minutes since your rework-claim. That completes this invocation.
0.5. **(all seats) Directed work — a human delegated something to you by name.** Issues: `glab issue list --assignee <your-bot-user> --label ready-for-agent -O json` — assigned to you but not yet claimed means delegated; claim it normally and work it, **regardless of tier cap or seat economy** (the maintainer outranks every rule). MRs: any open MR whose reviewer field names your bot user without your `review-claim:` comment is a directed review → `REVIEWING.md`. Conversely, skip MRs whose reviewer field names a *different* bot with no claim yet — they are directed elsewhere.
1. **(frontier and standard seats) Reviews** — `glab mr list --label review:frontier -F json` then `--label review:light`. Skip any MR labeled `changes-requested` (it is with its author), and any MR whose comments hold a `review-claim:` from another instance less than 24 hours old with no outcome yet. The first survivor IS your work item — read `REVIEWING.md` beside this skill and follow it. Only an empty result moves you to the next queue; an MR's age or subject never disqualify it — with one exception: **never review an MR authored by your own bot user** (any instance) — reviewer and implementer should be different models. Skip your own and leave them for another seat or the maintainer, **unless the MR carries `review-floor`**: that is the maintainer declaring no other reviewer exists, and a fresh session of your own bot user may then review it (you bring context independence, not blind-spot independence — so the debt label is mandatory, see `REVIEWING.md`). A standard seat takes a `review:frontier` MR **only when that MR also carries the `review-floor` label** — the maintainer's declaration that the frontier model is unavailable. Merge it as normal, then label the merged MR `needs-frontier-review` so a frontier seat audits it later. Seat economy, mirrored: a frontier seat takes a `review:light` MR only when it has sat unclaimed for over 4 hours — fresh light reviews belong to standard seats.
2. **(frontier seats) Review debt** — `glab mr list --merged --label needs-frontier-review -F json`. Found one → `REVIEWING.md`.
3. **(frontier seats) Triage** — `glab issue list --label needs-triage -O json`. Fresh issues → invoke orchestr:route on each; tickets holding a completed, peer-confirmed report → spot-check it, make the decision it feeds, and close. Then restart at queue 1.
4. **(mechanical seats) Peer-check** — `glab issue list --label needs-peer-check -O json`. Skip any ticket whose report was produced by your own bot user (read the claim comments — checker and producer must be **different models**; same-model instances share blind spots). Claim per step 3 but with the **`peer-claim:`** prefix (`glab issue note <n> --message "peer-claim: $INSTANCE $(date -u +%FT%TZ)"` plus the assignee) — the producer's implementation `claim:` is a different phase and does not block you. Then verify the report by re-running its key commands (the diffs, `git cherry`, the greps) against the current repo. Confirmed → comment `peer-check: confirmed` with what you re-ran, swap `needs-peer-check` → `needs-triage`, unassign. Discrepancy → comment starting `peer-check: refuted` with the exact mismatch, swap `needs-peer-check` → `ready-for-agent`, unassign — it returns to the implementation queue with your findings as the correction brief. **Round bound**: if this ticket already carries a `peer-check: refuted` note from an earlier round, swap to `needs-triage` instead and attach both reports — two refutations mean the ticket needs a decision, not another lap. (The `confirmed`/`refuted` prefixes are load-bearing — the stats skill parses them.)
5. **Implementation** — one query per tier (label filters AND together), from your cap downward:

   ```bash
   glab issue list --label ready-for-agent --label tier:mechanical -O json
   ```

   Skip any candidate that has an assignee (unless its claim is abandoned — see step 3's staleness rule), or whose description's `Blocked by: #N` line names an issue still open (check each with `glab issue view N`). Take the first survivor.

   Seat economy: a standard seat takes a `tier:mechanical` ticket only when it has sat unclaimed for over 24 hours (check `created_at`) — fresher mechanical work belongs to the mechanical seats. The same aging rule lets a frontier seat take `tier:standard` and `tier:mechanical` work, and lets a standard or frontier seat take a `needs-peer-check` ticket no mechanical seat has verified in 24 hours (the peer-check floor: better a capable checker than none).

All queues empty → report "queue empty for <seat>" and stop. That is a valid completion.

glab quirk (do not "fix" for uniformity): `glab mr list` outputs JSON via `-F json`; `glab issue list` via `-O json`. Each command above already carries its correct flag.

## 3. Claim (collision-safe)

Once per session, before your first claim, generate your **instance id** — N sessions may share one bot user, and this is what tells them apart:

```bash
INSTANCE="<your-bot-user>/i-$(openssl rand -hex 2)"   # e.g. bot-minimax/i-9f3c
```

```bash
glab issue update <n> --assignee @me --unlabel ready-for-agent
glab issue note <n> --message "claim: $INSTANCE $(date -u +%FT%TZ)"
```

(Removing `ready-for-agent` at claim is load-bearing: assigned **with** the label = delegated-awaiting-pickup; assigned **without** it = in-flight claim.)

**Whenever you let a ticket go without finishing it — backing off, escalating, being outraced, or stopping for any reason — restore exactly the label you removed when you claimed it, as you unassign** (a `claim:`-phase release restores `ready-for-agent`; a `peer-claim:` release leaves `needs-peer-check` in place and adds nothing). A ticket with a tier label but neither the label nor an assignee is invisible to every seat and sits open forever. Reclaiming an abandoned claim (step 3's staleness rule) is the only case where the label stays off, because you are taking it over.

**Claims are phase-scoped**: compare only against comments carrying the *same prefix* as yours — `claim:` (working a ticket), `peer-claim:` (checking someone's report), `review-claim:`, `rework-claim:`. A producer's implementation `claim:` never blocks a later phase; only same-prefix claims contend.

Re-read `glab issue view <n> --comments`. If a same-prefix claim comment with any instance id other than yours predates yours, the ticket is theirs — comment "backing off — claimed first by <their instance id>" and return to step 2. When the earlier claim is a **different bot user**, also `glab issue update <n> --unassignee @me`; when it is another instance of **your own bot user**, leave the assignee in place — it is theirs as much as yours, and unassigning would strip the winner's claim.

A claim is **void** — regardless of age — once a later note reads `claim-release: <that instance id>`. Anyone may post one (the maintainer, or a seat that can prove the holder is gone), and the item is immediately takeable. This is how a claim held by a seat that ran out of capacity gets freed without waiting out the staleness window.

Abandoned claims: a claimed ticket whose newest note is over 24 hours old is a dead instance's (crash, power loss). Reclaim it — comment "reclaiming from <their instance id> (stale)", unassign them, then claim normally. This is the same staleness rule review-claims and rework-claims carry.

## 4. Work the ticket

- First, verify the premise: check the ticket's acceptance criteria against current `main`. If they already hold — the work landed some other way — post the evidence as a comment, unassign yourself, and swap `ready-for-agent` for `needs-triage`; triage confirms and closes, you don't.
- Isolate in a worktree (superpowers:using-git-worktrees). Every file you create or modify lives inside that worktree, the hub clone, or /tmp — nowhere else on the machine, unless the brief explicitly says so.
- The ticket's brief is the spec. Implement with mattpocock-skills:tdd when the bar is expressible as tests.
- Loop until every command in the ticket's `## Verification` section passes **verbatim** — green means actual command output you ran, never expectation.
- If the bar will not pass after honest attempts, escalate: move the tier label one step up (already `tier:frontier`? swap `ready-for-agent` → `ready-for-human` instead — there is no higher tier), unassign yourself, restore `ready-for-agent`, and comment what failed with your branch name and the prefix `escalated:` so the next seat can count bounces. One bounce only — a ticket whose history already holds an `escalated:` note goes to `ready-for-human`, not up another tier.
- Too **big** rather than too hard? Split instead of escalating: create child issues each carrying `Parent: #<this>` as its first line plus a `relates_to` link (`glab api "projects/:id/issues/<child>/links" -X POST -f target_project_id=<numeric id from glab api projects/:id> -f target_issue_iid=<this> -f link_type=relates_to`), label them `needs-triage` — routing stays triage's call — then unassign and swap this ticket's `ready-for-agent` → `needs-triage` so triage can turn it into a held tracking node.

## 5. Hand off

- Report-only tickets (the brief's deliverable is a comment, no MR): post the report, then hand off by label — mechanical seats swap `ready-for-agent` → `needs-peer-check` (a different-model seat verifies before triage consumes it); standard and frontier seats swap `ready-for-agent` → `needs-triage`. Unassign yourself and stop — closing is triage's call, never yours.
- Open an MR with `Closes #<n>` and copy the issue's `review:*` label onto the MR — that label is what puts it in a reviewer's queue 1. If the issue carries none (directed work skips triage), apply `review:frontier`; an MR with no `review:*` label is in nobody's queue and you may not merge your own.
- Post the report comment on the MR (required shape — the **Not verified** section is mandatory; unverifiable criteria surfaced here are how humans catch what agents cannot):

```markdown
## Done
<what changed, one paragraph>

## Verified
<commands run + actual results>

## Not verified
<anything you could not exercise: UI click-throughs, prod-only behavior, external services. Write "nothing" only if truly nothing.>
```

- Tick the acceptance-criteria checkboxes you actually verified (`- [x]` in the issue description) — a visual mirror of `## Verified`, nothing more; review still gates.
- Record your clock: `glab issue note <n> --message "/spend <minutes>m"` **as its own note** (quick actions mixed with text post as literal text). Minutes = `date -u +%s` now minus the timestamp **you wrote inside this session's claim comment** — run the arithmetic, never estimate; the stats audit compares your value against the server's note timestamps and flags invented numbers. Peer-checkers do the same when finishing a check.
- Clean your bench: the branch is pushed, so remove your worktree (`git worktree remove <path>`) and delete the local branch copy (`git branch -d <branch>` from the hub clone). Rework re-creates a worktree from the remote branch.
- Leave the MR open — **the reviewer merges** (the project deletes the remote source branch on merge). Your ticket is finished when the MR is open, labeled, and the report is posted.

## Reviewing

Holding work from queues 1–2? Read `REVIEWING.md` beside this skill and follow it — load it only then.
