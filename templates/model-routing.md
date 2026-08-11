# Model routing

This repo routes agent work by capability tier. The logic lives in the
**orchestr** plugin (skills: `route`, `next-ticket`, `init`); this file is the
per-repo data those skills read.

## Labels (canonical → this repo)

| Canonical | Label here | Meaning |
| --- | --- | --- |
| frontier tier | `tier:frontier` | Judgment work — weak verification bar or wide blast radius |
| standard tier | `tier:standard` | Clear spec, moderate verification bar |
| mechanical tier | `tier:mechanical` | Checklist-ready: hard verification bar, narrow blast radius |
| frontier review | `review:frontier` | Merge requires a frontier-model review |
| light review | `review:light` | Standard-tier review suffices |
| review debt | `needs-frontier-review` | Merged without the required frontier review |

## Tier → model (ordered fallbacks)

| Tier | Models, in fallback order |
| --- | --- |
| frontier | <e.g. Fable → GPT-5.6 Sol → Opus> |
| standard | <e.g. Sonnet> |
| mechanical | <e.g. GLM-5.2, MiniMax-M3> |

## Seats

| Bot user | Model | Tier cap |
| --- | --- | --- |
| <bot-...> | <model> | <frontier/standard/mechanical> |

## Rules

- **Merge authority**: the reviewer merges; implementers leave MRs open.
- **Review floor**: when the frontier model is unavailable (the maintainer
  declares this), a standard seat reviews `review:frontier` MRs, merges, and
  labels the merged MR `needs-frontier-review`.
- **Escalation**: a failed verification bar bounces a ticket one tier up with a
  comment and branch link; the higher tier decides `ready-for-human`.
- **Token renewal**: bot access tokens expire <date>; rotate before then.
