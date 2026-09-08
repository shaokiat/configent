# Discovery Brief: Cloud Platform Support

**Prepared for:** Head of Platform Engineering, internal Cloud Platform team
**Prepared by:** Configent
**Date:** September 2026
**Engagement type:** Internal deployment-support assistant (`gcp-platform-support` / **DeployBot**)

> Written 2026-09-08, after week 1 shipped. It is dated deliberately: the pipeline was built
> from `docs/support-agent-plan.md` without a brief, and the gap showed up as a product bug —
> see *Pain Points 4* and D9 in [`docs/decisions.md`](../docs/decisions.md).

---

## Stakeholders

| Role | Name | Concern |
|------|------|---------|
| Head of Platform Engineering | Mei Tan | Interrupt load on a 6-person team; onboarding time for new service owners |
| Platform on-call engineer | Rotating | Wants a triage queue worth reading — not one padded with noise |
| Service owners (end users) | ~120 app engineers | Get unblocked mid-deploy, in seconds, without filing anything |
| Security / IAM reviewer | Daniel Cho | No advice that widens a role binding; no invented policy behaviour |

---

## Pain Points

1. **Interrupt load.** The platform channel takes 40–60 questions a week, and the on-call
   engineer estimates well over half are answered verbatim by the Cloud Run, GKE or IAM
   documentation. Each one costs a context switch during someone else's deploy.
2. **The docs are correct and unreadable in a hurry.** Google's documentation has the answer;
   an engineer with a failing deploy and a red CI pipeline does not have fifteen minutes to
   find the page.
3. **Wrong answers are expensive.** A plausible, confidently stated default or limit that
   isn't real sends an engineer down a debugging path that costs hours. A general-purpose
   chatbot is worse than nothing here — it is fluent about Kubernetes in general and wrong
   about GKE in particular.
4. **The queue has to stay trustworthy.** The team will only work a ticket queue it believes
   in. A queue holding greetings, thanks, and follow-up questions gets skimmed, then ignored,
   and the deflection number becomes meaningless. This is the requirement most easily lost:
   it is a property of what *doesn't* reach the queue.

---

## Current Process

1. Service owner hits a deploy error or a permissions failure.
2. Posts in the platform Slack channel, often as a pasted error string with no question.
3. On-call engineer context-switches, recognises it (usually), finds the doc page, replies.
4. If it needs project state — quota, IAM policy, cluster, billing — it becomes a real ticket,
   re-interviewed from scratch because the Slack thread has no structure.
5. Median unblock: minutes when someone is free, hours when nobody is.

---

## What the assistant is for

**Deflect the documented questions, and protect the queue that catches the rest.**

The corpus is public Cloud Run / GKE / IAM documentation (D1). It contains nothing about any
user's project, so the split is structural rather than staged:

- *"What does the platform do?"* — answerable, with citations.
- *"What is **my** project doing?"* — unanswerable by construction, however relevant the
  retrieved passages look.

An escalation is the product working, not the product failing. An escalation on `hi` is the
product failing.

---

## The user

An internal platform engineer, **mid-task and usually blocked**. They are not filing a support
request; they are trying to get unstuck in thirty seconds. Design consequences:

- They type like they're in Slack: fragments, follow-ups, `thanks`, a pasted stack trace.
- They read the first line and leave. Length is a cost, not thoroughness.
- They will test the edges in the first minute — `what can you do?` — and judge the whole
  system by that answer.
- They will not re-read a citation, but they will trust the assistant more for having one.

---

## Canonical session

The design unit is a **session by one blocked engineer**, not a single question. Every
requirement below is visible in this one dialogue:

| # | User | Expected behaviour |
|---|---|---|
| 1 | `hey` | One line naming the scope. No retrieval, no ticket. |
| 2 | `cloud run deploy failing, container failed to start and listen on the port defined by PORT` | Answer from the troubleshooting doc, cited. |
| 3 | `so is that the same as the health check timing out?` | A follow-up on the previous answer — resolve it in context, or ask one clarifying question. Not a ticket. |
| 4 | `ok that fixed it. can you bump my instance quota in europe-west1? deploy is blocked` | Needs a human. Offer a drafted ticket — `quota_or_billing`, `priority: high` (they said blocked) — and file it on confirmation. |
| 5 | `thanks` | Acknowledge. Nothing else happens. |

Turns 1, 3 and 5 are the ones the week-1 pipeline gets wrong, and none of them appear in
`evals/gcp-platform-support/golden.jsonl` — which is why the bug reached a live demo.

---

## Success Criteria

- **Deflection:** ≥ 60% of sessions that ask a documented question end without a ticket.
- **Queue precision:** ≥ 90% of filed tickets are questions a platform engineer must
  personally action. *Greetings, thanks, meta-questions and follow-ups never file a ticket.*
- **No invented facts:** zero answers stating a default, limit, error string or role name
  absent from a cited passage. Measured on the golden set, not asserted.
- **Escalation recall over precision:** of the questions that genuinely need a human, ≥ 95%
  reach one. A false answer costs more than a false escalate (see the asymmetry section in
  `docs/support-agent-plan.md`) — but "escalate everything" is not how it is bought.
- **Time to answer:** P90 < 10s for answerable questions; non-questions answer immediately.
- **Consent:** no ticket is filed without the user seeing the draft and agreeing.

---

## Proposed Scope (Phase 1 POC)

- Ingest: 10 curated public Google Cloud documents covering Cloud Run, GKE and IAM
  (CC BY 4.0, attributed per file).
- Pipeline: `retrieve → score → branch` with the escalate/answer decision made in Python
  (D2), a third `converse` outcome for non-support turns (D9), and a step trail rendered in
  the UI.
- Escalation: structured ticket drafted by a model, filed by Python over real HTTP against
  `apps/mockticket`, exactly once (D4), on user confirmation.
- Eval: 25–30 golden cases across all three outcomes, plus the threshold sweep.
- Out of scope: live doc sync, project-state integration (quota/IAM/billing APIs), auth and
  identity, Slack delivery, products outside Cloud Run / GKE / IAM.

---

## Open Questions

1. Confirming a ticket costs the blocked user an extra turn. Is one-click confirmation
   enough, or should high-priority production-impact cases file immediately and offer an
   undo?
2. Should a repeated unanswerable question in one conversation attach to the open ticket
   rather than file a second? (Currently a known gap — one ticket per run, not per
   conversation.)
3. Does a `docs_gap` ticket go to the same queue as `account_config`? They have different
   readers and very different urgency.
4. What is the acceptable daily spend ceiling once this is in front of 120 engineers rather
   than a demo?
