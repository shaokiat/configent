# Model cost and citations: the original method against numbered markers, 2026-10-11

Nine demo questions (DeployBot and PitWall), three passes each, so 27 turns per setup, all through
OpenRouter. Produced by `evals/model_cost.py` against a running API.

| Setup | Code | Answer model | Structured calls | Citations |
|---|---|---|---|---|
| **A. Original** | `b0835d9`, `structured_model` removed | Haiku 4.5 | Haiku 4.5 | API: `search_result` blocks (P4) |
| **B. Split** | `dd51822` | Haiku 4.5 | DeepSeek V4.1 Flash | `[n]` markers parsed in Python (D15) |
| **C. All DeepSeek** | `dd51822`, `model` set to DeepSeek | DeepSeek V4.1 Flash | DeepSeek V4.1 Flash | `[n]` markers (D15) |

"Structured calls" means grading, query rewriting, SQL generation and repair, and the ticket draft.

## Result

| | A. Original | B. Split | C. All DeepSeek |
|---|---|---|---|
| Billed by OpenRouter, 27 turns | $0.1632 | $0.0462 | **$0.0069** |
| Billed per turn | $0.0060 | $0.0017 | **$0.00026** |
| Against the original | — | −72% (3.5× cheaper) | **−96% (24× cheaper)** |
| Routed as expected | 27/27 | 27/27 | 27/27 |
| Expected fact in the answer | 15/15 | 15/15 | 15/15 |
| Citations per answer | 1.9 | 2.5 | 3.1 |
| Citations naming no passage | — | 0 | 0 |
| App's estimate (D8) vs billed | +3% | −5% | +64% |

- **Every setup routed every turn as expected and stated every expected fact.** These are the
  answers, the greetings, and both ticket offers.
- **The saving comes in two steps.** Moving the structured calls off Haiku saves 72%. Grading
  carries all five passages and runs on every documents turn, so it was most of the cost. Moving
  the answer as well saves the rest.
- **Markers cite more.** The model cites claim by claim; API citations grouped more text per citation.
  None of the markers named a passage that did not exist.

## Per question

Mean app-estimated cost per turn, and mean citations per answer.

| Question | A | B | C | Citations A / B / C |
|---|---|---|---|---|
| My Cloud Run container fails to start — what does the PORT error mean? | $0.0089 | $0.0043 | $0.0008 | 3.7 / 4.0 / 4.3 |
| What's the default CPU limit for a Cloud Run instance? | $0.0083 | $0.0040 | $0.0004 | 2.0 / 3.0 / 3.3 |
| Why won't my GKE node pool scale down after I deleted the workload? | $0.0078 | $0.0040 | $0.0011 | 2.0 / 3.7 / 6.0 |
| hey | $0.0021 | $0.0002 | $0.0002 | — |
| Can you raise my Cloud Run instance quota for europe-west1? | $0.0056 | $0.0004 | $0.0002 | — (ticket) |
| Who won the 2008 Monaco Grand Prix? | $0.0085 | $0.0007 | $0.0003 | 1 / 1 / 1 |
| Which constructor scored the most points in 2010? | $0.0055 | $0.0007 | $0.0004 | 1 / 1 / 1 |
| hi | $0.0041 | $0.0001 | $0.0001 | — |
| Can you add the 2024 season? | $0.0054 | $0.0003 | $0.0004 | — (ticket) |

## What the benchmark found and fixed first

The first DeepSeek runs failed in two ways. Both are fixed in `dd51822`, and the numbers above
come from after the fixes.

- **Empty JSON (2 of 18 turns).** DeepSeek reasons by default, and on a grading call it spent all of
  `max_tokens` on reasoning. The turn ended in a stream error. Structured calls now turn
  reasoning off and use strict schemas: 0 failures in 16 tries.
- **Deciding before reasoning (24 of 27 routed).** With reasoning off, the model filled in `kind`
  before `reasoning`, because fields are written in schema order. It marked "2008 Monaco" a
  handoff, then wrote "2008 is newer than the last season… wait, 2008 is within range." Making
  `reasoning` the first field fixed it: 27 of 27.

## Limits

- **Small sample.** It covers 9 questions, 3 passes each. It shows direction and is not a benchmark.
- **The fact check is a substring match** ("1 vCPU", "Hamilton", "Red Bull"). It shows the answer
  holds the fact, not that the answer is otherwise right.
- **Citations are checked for validity, not support.** A marker names a real passage in every
  case. Whether that passage says what the sentence does is the gap D15 records, and nothing
  here measures it.
- **DeepSeek is priced from the list in `config/pricing/claude.yaml`.** OpenRouter routed it to
  providers that bill less (DigitalOcean, CoreWeave), so the app overstates its cost by 64%.
  Haiku's estimate is within 5%.
