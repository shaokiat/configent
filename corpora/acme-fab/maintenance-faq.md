# PX-900 Maintenance FAQ

**Document ID:** PX900-FAQ-Rev2
**Revision Date:** March 2026

---

## Scheduled Maintenance

### Q: How often does the chamber seal need to be replaced?

The chamber seal (PX900-SEAL-A2) must be replaced every 1,200 RF hours. This is specified in
the PX-900 Maintenance Manual (PX900-MM-Rev4, §2.4). The RF-hour counter is shown on the
controller under **Logs > RF Hours**.

You can set a maintenance reminder in the controller: navigate to **Maintenance > Schedules**
and enter 1,200 hours as the seal replacement interval. The tool will display a yellow warning
at 1,150 hours and a red alert at 1,200 hours.

### Q: Can I extend the chamber seal replacement interval?

No. The 1,200 RF-hour interval is not negotiable from a warranty perspective. Acme's
materials qualification data shows seal degradation accelerates significantly beyond 1,200 hours
under fluorine process conditions. Some customers operating exclusively in non-fluorine chemistries
(e.g., Cl₂/BCl₃ only) have requested extensions; these require written approval from Acme
Engineering and are handled case-by-case.

### Q: How long does a chamber seal replacement take?

A trained field service engineer can complete the replacement in 4–6 hours including:
- Vent to nitrogen (30–45 minutes)
- Seal replacement and torque (1 hour)
- Pump-down to base pressure (2–3 hours)
- Verification recipe run (30 minutes)

Under a Tier 1 Gold contract, parts and labour are included. Under Tier 2 and below, labour
is billed at the current T&M rate.

### Q: What other parts are on the same 1,200 RF-hour schedule?

The exhaust isolation valve seat (PX900-VALVE-S1) is also replaced at 1,200 RF hours.
Both items can be done in the same maintenance window to minimise downtime.

---

## Error Codes

### Q: What is error E-417 and what should I do?

Error E-417 is a helium backside cooling leak alarm. See the Troubleshooting Guide
(PX900-TG-Rev3) for the full procedure. The controller will auto-abort the process. Perform a
controlled vent to nitrogen and call Acme Field Service.

### Q: The tool is showing E-403 (base pressure not reached). What should I check first?

E-403 usually indicates a vacuum leak. The most common causes in order of likelihood:

1. **Chamber seal due for replacement** — if you are near or past the 1,200 RF-hour interval,
   this is the first thing to check.
2. **O-ring damage** — inspect the upper electrode O-ring and gate valve O-ring.
3. **Gas line fitting loose** — check all VCR fittings accessible from outside the chamber.
4. **Exhaust isolation valve seat worn** — also replaced at 1,200 RF hours.

If none of the above resolve E-403, contact Acme Field Service for a detailed leak check.

---

## Parts Questions

### Q: Where do I find the part number for the chamber seal?

The chamber seal kit for the PX-900 is part number PX900-SEAL-A2. It is listed in the Acme
Spare Parts Catalog (SPC-2026). You can get a price and lead time quote via the customer portal
or call 1-800-ACM-PART.

### Q: Can I use a third-party chamber seal?

No. Third-party seals are not rated for the fluorine chemistry used in silicon nitride etch
processes and will void the chamber warranty. Always use Acme-genuine PX900-SEAL-A2.

### Q: What is the lead time for PX900-SEAL-A2?

Standard lead time is 21 days. For customers with Tier 1 Gold contracts, Acme maintains a
regional spare parts inventory that typically allows same-day or next-day exchange for the
chamber seal kit. Consult your account manager to confirm availability in your region.

---

## Service Contracts

### Q: What is the fastest response time I can get for a tool-down situation?

Under a Tier 1 Gold contract, response time is 4 business hours. With the 24/7 add-on,
response time drops to 2 calendar hours regardless of time of day. See the Service Contracts
FAQ (SC-FAQ-Rev5) for details.

### Q: My Tier 1 engineer didn't arrive within 4 hours. What can I do?

Log the SLA breach via the support portal within 5 business days. You are entitled to a credit
equal to one month's contract fee. For critical fabs with the 24/7 add-on, the escalation path
is to call the emergency line again and request a supervisor.

*© 2026 Acme Fab Equipment.*
