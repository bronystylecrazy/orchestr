---
name: route
description: Use when triaging issues that agents will implement — deciding which model tier gets a ticket, or when a ticket needs tier and review labels before it can be ready-for-agent.
---

# Route

Triage-time routing: give each issue a tier label, a review label, and an executable brief so an idle seat can pull it. Routing is frontier-tier work — a seat below frontier tier hands `needs-triage` issues back rather than routing them, and no seat re-routes its own ticket.

## Read first

- The repo's `docs/agents/model-routing.md` — this project's label strings, tier→model table, and seat list. Missing? Run orchestr:init first.
- The repo's `docs/agents/issue-tracker.md` — tracker CLI conventions (mattpocock-skills layer).

## The routing judgment

Judge the **verification bar** and the **blast radius** — never felt difficulty or ticket size:

| Tier | Verification bar | Blast radius |
| --- | --- | --- |
| `tier:mechanical` | A checklist: exact commands whose pass/fail is unambiguous | Narrow — worst case is contained and reversible |
| `tier:standard` | Clear spec, moderate bar; some inference, no design decisions | Moderate |
| `tier:frontier` | Design judgment, ambiguous spec, or taste required | Wide — auth, security, data loss, migrations, public API |

Before settling a tier, **try to demote**: strengthen the bar — write acceptance criteria and exact verification commands — until the ticket drops a tier. That is where the token savings live. A ticket that resists a mechanical bar is telling you its true tier.

Review axis: default `review:frontier`. Apply `review:light` only when the worst case is trivially reversible (docs, copy, config bumps).

## Ticket brief (required shape)

Rewrite the issue description so a seat can execute it with no other context:

```markdown
## Context
<what exists, where, and why this change>

## Acceptance criteria
<for tier:mechanical: a literal checklist>

## Verification
<exact copy-pasteable commands + the output that means pass>

## Out of scope
<the adjacent work this ticket must not touch>
```

If the ticket depends on another open issue, put `Blocked by: #N` as the first line (this instance is GitLab CE — there are no native blocking links).

## Done when

The issue carries a tier label + a review label + `ready-for-agent`, and its description matches the brief shape. An issue that cannot reach that shape is not agent-ready: label it `needs-info` or `ready-for-human` instead and comment why.
