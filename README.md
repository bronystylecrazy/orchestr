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
