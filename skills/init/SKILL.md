---
name: init
description: Use when onboarding a project to orchestr routing — the tier labels are missing, there is no docs/agents/model-routing.md, or a new repo's tracker needs setting up for tiered agent seats.
---

# Init

Bootstrap a repo for tier routing. Idempotent — safe to re-run; each step checks before it creates.

## 1. Labels

`glab label list --per-page 100` first, then create only the missing ones:

```bash
glab label create --name "tier:frontier"        --color "#8B008B" --description "Judgment work — weak verification bar or wide blast radius"
glab label create --name "tier:standard"        --color "#1D76DB" --description "Clear spec, moderate verification bar"
glab label create --name "tier:mechanical"      --color "#0E8A16" --description "Checklist-ready: hard verification bar, narrow blast radius"
glab label create --name "review:frontier"      --color "#FF8C00" --description "Merge requires a frontier-model review"
glab label create --name "review:light"         --color "#FBCA04" --description "Standard-tier review suffices"
glab label create --name "needs-frontier-review" --color "#D93F0B" --description "Merged without the required frontier review (debt)"
```

The five mattpocock triage labels are prerequisites (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`); create any of those that are missing too, with the descriptions from the repo's `docs/agents/triage-labels.md`.

## 2. Tracker doc check

The repo's `docs/agents/issue-tracker.md` (mattpocock layer) may carry a stale
glab flag that breaks mechanical seats:

```bash
grep -n -- '-F json' docs/agents/issue-tracker.md
```

Any hits → change them to `-O json` (glab 1.111+'s JSON output flag;
`-F/--output-format` only accepts `details|ids|urls`) and land the fix through
the repo's MR conventions — same MR as step 3 is fine.

## 3. Repo doc

Copy `templates/model-routing.md` from this plugin's root into the repo as `docs/agents/model-routing.md`, then fill in the per-repo data: the tier→model table and the **Seats** table (only bot users that actually have Developer access to this project). Land it through the repo's normal MR conventions.

## 4. Pointer

Add to the repo CLAUDE.md's agent-skills section:

```markdown
### Model routing

Issues route to model seats by tier/review labels via the orchestr plugin
(`/orchestr:route`, `/orchestr:next-ticket`). Per-repo data lives in
`docs/agents/model-routing.md`.
```

## Done when

All eleven labels exist on the project, `issue-tracker.md` has no `-F json` hits, `docs/agents/model-routing.md` is committed, and CLAUDE.md points at it.
