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

Work the queues in this order. Standard seats start at queue 1; mechanical
seats start at queue 4.

1. **(frontier and standard seats) Reviews** — `glab mr list --label review:frontier -F json` then `--label review:light`. Any MR these queries return IS your work item: take the first and jump to **Reviewing** below. Only an empty result moves you to the next queue — the MR's author, age, or subject never disqualify it. A standard seat takes `review:frontier` MRs only under the review-floor rule in `model-routing.md`.
2. **(frontier seats) Review debt** — `glab mr list --merged --label needs-frontier-review -F json`. Found one → **Reviewing**.
3. **(frontier seats) Triage** — `glab issue list --label needs-triage -O json`. Found issues → invoke orchestr:route on each, then restart at queue 1.
4. **Implementation** — one query per tier (label filters AND together), from your cap downward:

   ```bash
   glab issue list --label ready-for-agent --label tier:mechanical -O json
   ```

   Skip any candidate that has an assignee, or whose description's `Blocked by: #N` line names an issue still open (check each with `glab issue view N`). Take the first survivor.

   Seat economy: a standard seat takes a `tier:mechanical` ticket only when it has sat unclaimed for over 24 hours (check `created_at`) — fresher mechanical work belongs to the mechanical seats.

All queues empty → report "queue empty for <seat>" and stop. That is a valid completion.

glab quirk (do not "fix" for uniformity): `glab mr list` outputs JSON via `-F json`; `glab issue list` via `-O json`. Each command above already carries its correct flag.

## 3. Claim (collision-safe)

```bash
glab issue update <n> --assignee @me
glab issue note <n> --message "claim: <your-bot-user> $(date -u +%FT%TZ)"
```

Re-read `glab issue view <n> --comments`. If a claim comment from another user predates yours, the ticket is theirs: `glab issue update <n> --unassignee @me`, comment "backing off — claimed first by <user>", and return to step 2.

## 4. Work the ticket

- First, verify the premise: check the ticket's acceptance criteria against current `main`. If they already hold — the work landed some other way — post the evidence as a comment, unassign yourself, and swap `ready-for-agent` for `needs-triage`; triage confirms and closes, you don't.
- Isolate in a worktree (superpowers:using-git-worktrees).
- The ticket's brief is the spec. Implement with mattpocock-skills:tdd when the bar is expressible as tests.
- Loop until every command in the ticket's `## Verification` section passes **verbatim** — green means actual command output you ran, never expectation.
- If the bar will not pass after honest attempts, escalate: move the tier label one step up, unassign yourself, comment what failed with your branch name, and stop. One bounce only — the higher tier decides whether it becomes `ready-for-human`.

## 5. Hand off

- Open an MR with `Closes #<n>` and copy the issue's `review:*` label onto the MR — that label is what puts it in a reviewer's queue 1.
- Post the report comment on the MR (required shape — the **Not verified** section is mandatory; unverifiable criteria surfaced here are how humans catch what agents cannot):

```markdown
## Done
<what changed, one paragraph>

## Verified
<commands run + actual results>

## Not verified
<anything you could not exercise: UI click-throughs, prod-only behavior, external services. Write "nothing" only if truly nothing.>
```

- Leave the MR open — **the reviewer merges**. Your ticket is finished when the MR is open, labeled, and the report is posted.

## Reviewing (frontier seats, and standard seats on the review floor)

1. Review the MR against its originating issue's brief with mattpocock-skills:code-review.
2. Findings → comment them on the MR and leave it open for the implementer; clean → approve and merge.
3. **`glab mr merge` lies** — it prints success on failure. After merging, verify with `glab api projects/:id/merge_requests/<iid>` and confirm `state == "merged"` and `merged_at` is set.
4. Review-floor case (standard seat merging a `review:frontier` MR while the frontier model is unavailable): after the verified merge, label the merged MR `needs-frontier-review` — that is the debt queue.
5. Review-debt case (merged MR): review the merged diff; findings become new issues labeled `needs-triage`; finish by removing `needs-frontier-review` from the MR.
