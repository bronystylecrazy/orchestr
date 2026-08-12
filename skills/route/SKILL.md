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

## Announce the routing

Finish every routing with a note — `glab issue note <n> --message "routed: <tier>, <review label>"`. This is not ceremony: label edits emit no GitLab event, and the seats' event-gated pollers wake on this note. It doubles as the routing audit line.

## Estimate

After routing, post `/estimate <n>m` **as its own note** (quick actions mixed with text post as literal text). Seed from the scorecard's median cycle for the tier when you have it; defaults otherwise: mechanical 20m, standard 60m, frontier 2h. Override only when the brief is unusual.

## Decomposing a feature

A feature too big for one ticket becomes a **parent tracking node** plus routed children:

- Parent: keep it labeled (tier/review) but **never `ready-for-agent`** — it is not claimable work; it is where progress and the final close live. Triage closes it when the last child lands.
- Each child: full brief of its own, `Parent: #<parent>` as the description's first line, a `relates_to` link for the sidebar (`glab api "projects/:id/issues/<parent>/links" -X POST -f target_project_id=<numeric id from glab api projects/:id> -f target_issue_iid=<child> -f link_type=relates_to`), then route it like any ticket. `Blocked by: #<sibling>` lines order them.

(CE note: `/set_parent`//`/add_child` silently no-op for issue→issue on Free tier — the link + `Parent:` line convention IS the hierarchy here.)

## Done when

The issue carries a tier label + a review label + `ready-for-agent`, an estimate, and its description matches the brief shape. An issue that cannot reach that shape is not agent-ready: label it `needs-info` or `ready-for-human` instead and comment why.
