# Retrieval eval, gcp-platform-support, 2026-10-08

Git SHA `f4f50db`. n = 9 questions with expected citations (golden set rows with none are skipped). One question moves a metric by 11.1 points.

| Variant | top_k | keyword | rrf_k | floor | recall@k | MRR | Missed |
|---|---|---|---|---|---|---|---|
| Level 1, dense only | 5 | off | 60 | 0.3 | 0.889 | 0.889 | gcp-g5 |
| Level 1, dense only | 10 | off | 60 | 0.3 | 0.889 | 0.889 | gcp-g5 |
| Level 2, dense + keyword | 5 | on | 60 | 0.3 | 1.000 | 0.917 | - |
| Level 2, dense + keyword | 10 | on | 60 | 0.3 | 1.000 | 0.917 | - |

Level 1 passes `[question]` only, so keyword search has nothing to act on and the keyword-off rows are
the Level 1 path. Level 2 rows pass the question plus keywords made without a model (words over 4
letters, OR-ed); there is no rewrite set, so this is keyword fusion only. Embeddings use the client's
`voyage-3`; the query vectors are computed once and reused across variants.

## Reading

n = 9, so a single question moves a metric by 11.1 points: this is direction, not a benchmark.
Eight of nine questions have the expected document at rank 1 by dense search alone. The one miss, gcp-g5
(`iam-overview`), has a cosine of 0.27, below the 0.3 `retrieval_drop_floor`, so the floor removes it
(unfloored it is rank 3). Keyword fusion recovers it (recall 0.889 to 1.0). `top_k` 5 vs 10 changes nothing.

## Why reranking (Part 2) was not built

Recall@5 is 1.0 and MRR 0.917 on the Level 2 path. On Level 1 the only loss is the g5 floor drop, which
a reranker cannot fix under the issue's recommended design (floor on cosine, order by rerank): the chunk
is gone before reordering. The ordering already puts the expected document first in 8 of 9 cases, so
there is no ordering error to correct. Reranking would add a network call and a price row for no
measurable gain on this corpus. Revisit if the golden set grows or the corpus gets larger.
