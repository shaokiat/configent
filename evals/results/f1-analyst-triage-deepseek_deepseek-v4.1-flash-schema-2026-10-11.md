# f1-analyst triage, deepseek/deepseek-v4.1-flash, variant=schema, evidence=False

git b66869020933a7955882adc112a8caf3d37c15d5, 2026-10-11, 22 cases

| metric | value |
|---|---|
| accuracy | 90.9% (20/22) |
| outcomes | {'-': 22} |
| cost per question (mean / p95) | $0.0005 / $0.0012 |
| model latency per question, ms (mean / p95) | 2753 / 4777 |
| cache read / write tokens | 59648 / 0 |

| expected \ got | question | conversation | handoff | none |
|---|---|---|---|---|
| question | 9 | 1 | 0 | 0 |
| conversation | 0 | 6 | 0 | 0 |
| handoff | 1 | 0 | 5 | 0 |
