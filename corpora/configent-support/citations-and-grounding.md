# Configent: Citations and Grounding

**Document ID:** DOC-CITE-Rev1
**Revision Date:** June 2026

---

## 1. Why Grounding Matters

An enterprise assistant is only useful if its answers can be trusted. Configent assistants are
grounded: they answer from the client's documents, not from the model's general training
knowledge, and they show their work so a user can verify every claim.

---

## 2. How Citations Work

Every answer cites its sources through a `search_result_location` block so the cited text appears verbatim in the source document. When the agent uses a passage returned by `search_docs`, the
platform attaches a citation that records which document the passage came from and the exact text
that was cited. The UI renders these as inline references the user can expand.

Because the cited text must appear verbatim in the source, a citation cannot point at something
the document does not actually say. This makes hallucinated references detectable: if the cited
text is not present in the source, the citation is invalid.

---

## 3. What the Assistant Does When It Cannot Answer

If retrieval returns nothing relevant to the question, the assistant is instructed to say it does
not know rather than guess. A confident answer with no supporting source is worse than an honest
"I don't have that information," because users act on what the assistant tells them.

For Configent Support specifically, when a question cannot be answered from the documentation —
for example a bug report, a billing dispute, or a feature request — the assistant offers to file
a support ticket instead of inventing an answer.

---

## 4. Evaluating Grounding

The platform supports an offline eval: a golden set of questions, each with an expected answer
and the source it should cite. A judge model scores whether each answer is grounded in the cited
material. This lets a team measure citation quality before shipping a change, not after a user
reports a wrong answer.

*© 2026 Configent.*
