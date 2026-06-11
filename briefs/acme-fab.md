# Discovery Brief: Acme Fab Equipment

**Prepared for:** VP of Customer Success, Acme Fab Equipment
**Prepared by:** Configent
**Date:** June 2026
**Engagement type:** AI-assisted self-service knowledge portal

---

## Stakeholders

| Role | Name | Concern |
|------|------|---------|
| VP, Customer Success | Sandra Lim | Reduce Tier-2 escalations; improve CSAT |
| Field Service Director | Raj Patel | Free engineers from repetitive FAQ calls |
| IT Security | Daniel Cho | Data residency, access controls |
| Equipment Operators (end users) | — | Fast, reliable answers during fab runs |

---

## Pain Points

1. **Escalation overload.** 60–70% of customer support tickets are answered by the same three
   maintenance manuals. Field engineers spend 2+ hours per shift answering calls that a trained
   operator could resolve alone if they could find the right page.
2. **Documentation is fragmented.** Equipment manuals, spare-parts catalogs, and troubleshooting
   guides live in separate SharePoint folders by product line. No search, no cross-references,
   no single place to ask a question.
3. **Tribal knowledge risk.** Three senior engineers hold the institutional knowledge for legacy
   product lines (PX-700, LT-100). Two are approaching retirement.
4. **Slow parts quoting.** Customers asking "how much for 50 of part X?" wait 24–48 hours for a
   sales response that could be automated from a price list.

---

## Current Process

1. Operator notices an issue on the fab floor (error code, abnormal readout).
2. Operator calls the Acme 1-800 support line.
3. Support agent searches SharePoint (5–15 min), escalates if uncertain.
4. Field engineer calls back if needed (Tier-1 SLA: 4 business hours).
5. Operator resumes operation, typically 1–3 hours after the initial call.

---

## Success Criteria

- **Deflection rate:** ≥50% of Tier-1 tickets resolved without human intervention after 90 days.
- **Time to answer:** P90 < 30 seconds for questions answerable from the corpus.
- **Citation accuracy:** Every answer cites a specific document and section; zero hallucinated
  procedures.
- **Parts quoting:** Operators can get a unit price, volume discount, and lead time for any
  catalogued part in < 60 seconds.

---

## Proposed Scope (Phase 1 POC)

- Ingest: equipment manuals, maintenance FAQs, spare-parts catalog, troubleshooting guides for
  the PX-900 and LT-200 product lines (10–15 documents, ~50K tokens).
- Agent tools: `search_docs` (RAG over corpus), `get_document` (full document retrieval),
  `pricing_lookup` (mock canned pricing API for PX-900/LT-200 parts).
- Deployment: single branded chat UI at `/c/acme-fab`, accessible on the customer portal.
- Eval: 25–40 golden Q&A pairs; target answer quality ≥ 90% and retrieval hit@5 ≥ 95%.
- Out of scope: real ERP integration, user auth, multi-language support, voice interface.

---

## Open Questions

1. Does SharePoint export to PDF, or do we need to scrape HTML?
2. Is the parts pricing data exportable as CSV/JSON, or does it require CRM integration?
3. What is the acceptable daily spend ceiling per client for the demo period?
