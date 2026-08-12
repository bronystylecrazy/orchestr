---
name: stats
description: Use when the user asks for the orchestr scorecard, fleet metrics, seat performance, refute or rework rates, queue health, or where work is stuck.
---

# Stats

Read-only scorecard computed from the tracker's own records (claims, label
events, peer-check comments, merges). Any seat may run it.

## Run

From inside a clone of the target repo (glab must be authenticated):

```bash
python3 "<this skill's base directory>/scorecard.py" --days 7
```

`--days` widens or narrows the window.

## Present

1. Show the script's output verbatim in a code block.
2. Add a short interpretation — at most a few sentences: the current
   bottleneck queue, any seat whose refute or rework rate stands out, and
   which FLAGS deserve action.
3. Recommend, don't act: this skill changes nothing on the tracker. Tier-table
   changes or queue interventions are the maintainer's call (or a triage
   session's), informed by these numbers.

## Reading the columns

- **peer-ok / refuted** — peer-check outcomes per *producer*. Sustained-zero
  refutes argues for relaxing peer-check on that producer; a rising rate
  argues for tightening or demoting the work.
- **checks** — peer-checks performed per *checker* (their workload).
- **rework/MR** — mean `changes-requested` rounds per MR *author*. Low argues
  the seat can take harder work; high argues its briefs need sharper bars.
- **merges** — verified merges per *reviewer*.
- **med cycle** — median claim→close time per producing seat.
- **QUEUES** — depth and oldest item; the deepest-and-oldest queue is the
  system's current bottleneck (persistently the triage inbox → run more
  frontier triage sessions, not more implementers).
- **LEDGER** — per-seat session counts and token cost from
  `~/.config/orchestr/ledger/` (written by `bin/seat-loop.sh`; present only on
  the machine running the loops). Cost is API-equivalent dollars — seats on
  subscription plans bill by plan, so read it as relative effort, not invoice.
- **FLAGS** — specific stuck items: aging reviews, wedged peer-checks,
  untouched ready tickets, claimed-but-quiet tickets (possible dead instance).
