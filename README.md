# orchestr

Routes issue-tracker work to the right model tier for cost/quality efficiency.
Layers on [mattpocock-skills](https://github.com/mattpocock/skills): the five
canonical triage roles and the "repo doc maps canonical → local strings"
pattern are the only surfaces it depends on.

## The model

- **Labels are tier-indirect, never model-named** — `tier:frontier` /
  `tier:standard` / `tier:mechanical` plus a `review:*` axis. Models churn;
  labels don't. The tier→model mapping lives in each repo's
  `docs/agents/model-routing.md`.
- **Triage judges the verification bar + blast radius**, not felt difficulty,
  and strengthens bars to demote tickets down-tier — that's where token
  savings live.
- **Pull, not push** — an idle seat runs `/orchestr:next-ticket`: pick → claim
  (collision-safe) → implement to the ticket's verification bar → MR + report.
  The reviewer merges, never the implementer.
- **Attribution is per-model** — each seat is a GitLab bot user
  (`bot-fable`, `bot-glm`, …); assignee history is the data for tuning tiers.
- **Review debt is first-class** — work merged while the frontier model is
  over limit carries `needs-frontier-review` on the merged MR; frontier seats
  drain that queue first when idle.
- **Peer-check** — a mechanical seat's report is verified by a
  *different-model* mechanical seat (`needs-peer-check`) before triage spends
  frontier attention on it; same-model instances share blind spots, so the
  checker must be another bot user.

## The flow, start to finish

```
        issue filed
             │
      [needs-triage] ◀────────────────────────────┐
             │                                    │
   ➊ TRIAGE (frontier seat)                       │ confirmed reports
     judge bar + blast radius, write brief,       │ come back here for
     demote by strengthening the bar              │ the decision + close
             │                                    │
   [ready-for-agent + tier:X + review:X]          │
             │                                    │
   ➋ DISPATCH /next-ticket → claim (instance id)  │
             │                                    │
   ➌ WORK: premise-check → worktree → tdd         │
      → verification commands pass verbatim       │
             │                                    │
      ┌──────┴───────┐                            │
 report ticket    code ticket                     │
      │               │                           │
 mechanical seat?  ➎ MR + review:X label          │
  yes │  no           + Done/Verified/            │
      │   │             Not-verified report       │
 ➍ [needs-peer-    ┌──────┴──────────┐            │
    check]      findings          clean           │
 different-model   │                 │            │
 checker re-runs [changes-        approve +       │
 the commands     requested]      verified merge  │
   │       │       │ author's        │            │
confirmed refuted  │ queue 0:     issue closes    │
   │       │       │ fix, push,   via Closes #N   │
   └──▶────┼──────▶│ unlabel                      │
[needs-    │       └──▶ back to review            │
 triage]───┘                                      │
   └──────────────────────────────────────────────┘
```

1. **Triage** (frontier, manual — the pump): every issue is judged on
   *verification bar + blast radius*, rewritten into an executable brief
   (Context / Acceptance criteria / Verification / Out of scope), and
   labeled. The craft is demotion — sharpening the bar until a cheaper tier
   can safely own it. Can't reach brief shape → `needs-info` or
   `ready-for-human`.
2. **Dispatch**: idle seats pull, nothing is pushed. Queue order: **0** own
   `changes-requested` MRs (rework beats new work) → **1** reviews →
   **2** review debt → **3** triage inbox → **4** peer-check → **5**
   implementation (tier cap and below). Every claim is collision-safe via
   instance-id comments.
3. **Work**: verify the premise against main first (already landed →
   evidence + back to triage), then worktree + TDD until the brief's
   verification commands pass *verbatim*. Stuck → escalate one tier up,
   once.
4. **Peer-check**: a mechanical report is re-executed — not re-read — by a
   different-model mechanical seat before frontier attention touches it.
   Refutations become correction briefs automatically.
5. **Review & merge**: reviewer claims (`review-claim:`), reviews against
   the originating brief, then either labels `changes-requested` (→ author's
   queue 0, loops until clean) or merges with API verification. Implementers
   never merge; mechanical seats structurally can't. Frontier over limit →
   a standard seat is the floor and the merged MR carries
   `needs-frontier-review` debt.

The human appears at exactly three points: starting frontier triage sessions
(nothing moves without ticket supply), answering the maintainer-decision
lists that spec tickets produce, and holding or overriding anything
(remove `ready-for-agent` to pause; the maintainer outranks every rule).

## Skills

| Skill | When |
| --- | --- |
| `/orchestr:init` | Onboard a project: labels + `docs/agents/model-routing.md` |
| `/orchestr:route` | Triage-time: assign tier/review labels + executable brief |
| `/orchestr:next-ticket` | Idle seat: pull and work the next item |

## Seat setup (per machine/account)

1. Install this plugin (same as any Claude Code plugin).
2. Set that seat's bot token in the profile environment — never rewrite the
   machine's global glab auth:
   `export GITLAB_TOKEN=<bot token> GITLAB_HOST=<your gitlab host>`
3. Idle loop, once trusted: `/loop /orchestr:next-ticket`.

## Instances (N sessions per model)

Scale a seat by running N sessions with the **same** bot token — no extra
GitLab users. Each session generates a random instance id at startup
(`bot-minimax/i-9f3c`) and stamps it into claim comments; back-off compares
instance ids, so same-account sessions never collide. Permissions, tier cap,
and assignee attribution stay at the bot-user (model) level.

The flow is per-seat; instances multiply its concurrency:

- **Rework is seat-owned** — queue 0 matches MRs authored by the bot user,
  so any sibling instance can take over a `changes-requested` MR; a crashed
  instance never strands its work (the branch and findings live on the MR).
- **Peer-check does not scale with producer instances** — siblings can't
  check each other; scale the *checker* seat with the producers' output.
- **N instances pay off only when the seat's queues sustain ≥N items**;
  producers scale with triage floods, checkers with producer volume,
  reviewers rarely past one or two.

## Shared clone (multiple seats, one machine, one directory)

Seats may share a single repo clone: queries and doc reads run from it
concurrently, and each ticket is implemented in its own `git worktree`
(next-ticket step 4). The shared clone is a **hub, parked on the default
branch** — build, test, and branch-switch only inside your worktree, never in
the shared root. Identity stays per-session: each seat's `GITLAB_TOKEN` lives
in its own profile environment, never in a shared shell rc.
