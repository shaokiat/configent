# Discovery Brief: Meridian Insurance

**Prepared for:** Head of Claims Operations, Meridian Insurance
**Prepared by:** Configent
**Date:** June 2026
**Engagement type:** AI-assisted policyholder self-service portal

---

## Stakeholders

| Role | Name | Concern |
|------|------|---------|
| Head of Claims Operations | Patricia Walsh | Reduce call centre volume; improve first-contact resolution |
| Chief Underwriting Officer | Marcus Tran | Ensure AI does not misrepresent coverage; liability exposure |
| Legal & Compliance | Alicia Ng | Regulatory accuracy; audit trail for every AI-generated answer |
| Policyholders (end users) | — | Immediate, plain-English answers to coverage questions |

---

## Pain Points

1. **Call centre overload.** 40% of inbound calls are coverage queries answerable from the
   policy wording. Average handle time is 8 minutes; most agents look up the same five clauses
   repeatedly.
2. **Policy language is opaque.** HomeShield Plus wording runs to 34 pages of nested clauses.
   Policyholders cannot self-serve even when the answer is in the document, because they cannot
   find it or parse it.
3. **Claims misfiling.** 12% of claims are lodged against the wrong coverage type, requiring
   manual triage. A pre-claim coverage check would eliminate most of these.
4. **Underwriting inconsistency.** New underwriters apply flood and coastal risk rules
   inconsistently because the guidelines are in a separate document not linked from the quoting
   tool.

---

## Current Process

1. Policyholder calls (or emails) with a coverage question ("is my leaking ceiling covered?").
2. Call centre agent opens the policy wording PDF, searches by Ctrl-F.
3. Agent interprets the clause and gives a verbal answer (not recorded, not cited).
4. Policyholder proceeds (or misfiles a claim) based on the verbal answer.
5. If contested, the claims adjuster re-reads the original policy — sometimes reaching a
   different conclusion.

---

## Success Criteria

- **Coverage queries self-served:** ≥60% of coverage questions deflected to the AI portal
  without human involvement.
- **Citation completeness:** Every answer must cite the specific clause number and document
  section; the cited text must appear verbatim in the source.
- **Zero misrepresentation rate:** LLM judge score ≥ 4/5 on groundedness for all answers in
  the eval set; any answer citing a non-existent clause flagged and blocked.
- **Claims pre-screening:** Operator can ask "am I covered for X?" and receive a plain-English
  verdict + clause reference before filing.

---

## Proposed Scope (Phase 1 POC)

- Ingest: HomeShield Plus policy wording, claims process FAQ, underwriting guidelines, coverage
  exclusions list (10–15 documents, ~60K tokens).
- Agent tools: `search_docs` (RAG over corpus), `get_document` (full policy retrieval),
  `coverage_check` (mock canned decision table for common claim scenarios).
- Deployment: branded chat UI at `/c/meridian-insurance`.
- Eval: 25–40 golden Q&A pairs including 5 refusal cases; target answer quality ≥ 88% and
  retrieval hit@5 ≥ 90%.
- Out of scope: actual claims intake, real policy system integration, broker-facing portal,
  regulatory filing.

---

## Open Questions

1. Are policy wording documents the latest versions, or do we need to handle multiple effective
   dates?
2. What is the approval process for publishing AI-generated coverage guidance to policyholders?
3. Is there an existing DPA / data processing agreement template we should align to?
