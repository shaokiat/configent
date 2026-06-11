# Service Contracts and SLA FAQ

**Document ID:** SC-FAQ-Rev5
**Applies to:** All Acme Fab Equipment installations
**Revision Date:** February 2026

---

## General Questions

### Q: What service contract tiers does Acme offer?

Acme offers four contract tiers for all equipment:

| Tier | Description | Response Time | Coverage |
|------|-------------|--------------|---------|
| **Tier 1 — Gold** | Premium 24/7 on-site | 4 business hours | Parts + labour, PM included |
| **Tier 2 — Silver** | Business hours on-site | Next business day | Parts + labour |
| **Tier 3 — Bronze** | Remote support + parts | 2 business days remote | Parts only; labour T&M |
| **Tier 4 — Basic** | Phone/email support | 3 business days | Labour T&M only |

### Q: What does the Tier 1 response SLA mean exactly?

Field service response time for Tier 1 contracts is 4 business hours.

This means that from the moment a Tier-1 service request is registered in the Acme support
portal (or logged via the 1-800-ACM-SVC1 emergency line), a field service engineer will be
on-site within 4 business hours. Business hours are 08:00–18:00 local time, Monday through
Friday, excluding public holidays.

Note: "on-site" means the engineer has physically arrived at the customer facility, not that
the repair is complete. Repair time depends on parts availability and fault complexity.

### Q: Does the 4-hour SLA apply 24/7?

For Tier 1 contracts with the 24/7 add-on (SKU: SC-T1-24/7), the 4-business-hour SLA is
replaced with a **2-calendar-hour** SLA with no time-of-day restriction. This add-on is
available for critical fab lines where downtime costs exceed $10,000 per hour.

For standard Tier 1 (without the 24/7 add-on), out-of-hours calls received after 18:00 are
logged at 08:00 the next business day for SLA timing purposes.

### Q: What is covered under the Tier 1 Gold contract?

- All preventive maintenance visits per the published PM schedule
- All labour costs for corrective maintenance (emergency and scheduled)
- All Acme-genuine replacement parts (including consumables such as focus rings, O-rings, and
  the 1,200 RF-hour chamber seal kit PX900-SEAL-A2)
- 24-hour phone and remote diagnostic support

Not covered:
- Damage caused by customer modification to the equipment
- Process chemistry compatibility issues (consult Acme Process Engineering separately)
- Third-party peripheral equipment

### Q: Can I switch contract tiers mid-year?

Tier upgrades take effect immediately and are prorated. Tier downgrades take effect at the
next contract anniversary date. Contact your regional account manager.

---

## Response and Escalation

### Q: How do I log a Tier-1 service call?

1. **During business hours:** Call 1-800-ACM-SVC1, select option 2 for equipment emergencies.
   Have your tool serial number and current error code ready.
2. **Outside business hours (Tier 1 standard):** Call the same number; your request will be
   logged and the on-call engineer will call back within 30 minutes to assess remotely.
3. **Outside business hours (Tier 1 24/7 add-on):** Call 1-800-ACM-SVC1, select option 1
   for 24/7 critical response. On-site dispatch is initiated immediately.

### Q: What information should I have ready when calling?

- Tool serial number (found on the nameplate, front-left panel)
- Error code displayed on the controller touchscreen
- Brief description of the fault: when it occurred, what process was running
- Current safe state of the tool (vented? plasma off? wafer on ESC?)

### Q: What if the engineer doesn't arrive within 4 hours?

If the Tier-1 SLA is breached without prior notification and agreement, you are entitled to a
service credit equal to one month's contract fee. Log the breach via the support portal within
5 business days.

---

## Parts and Consumables

### Q: Are parts included in Tier 1?

Yes. All Acme-genuine parts consumed during both preventive and corrective maintenance are
included in the Tier 1 Gold contract. This includes high-consumption consumables:

| Part | P/N | Normal interval |
|------|-----|----------------|
| Chamber seal kit | PX900-SEAL-A2 | 1,200 RF hours |
| Focus ring | PX900-FOCUS-R3 | 300 RF hours |
| Upper electrode O-ring | PX900-ORING-U2 | 300 RF hours |

### Q: Can I buy spare parts without a service contract?

Yes. Parts are available through the Acme Spare Parts Catalog (SPC-2026) or via the customer
portal. Pricing and lead times are listed in the catalog; for volume pricing, use the
`pricing_lookup` tool or contact your account manager for a formal quote.

---

## Contract Renewal

### Q: When does my contract expire?

Contract expiry dates are listed in the Acme Customer Portal under **My Equipment > Service
Contracts**. Acme will send renewal reminders 90, 60, and 30 days before expiry.

### Q: What happens if my tool goes out of contract?

Out-of-contract tools receive phone/email support only. On-site visits are available on a
time-and-materials basis (current labour rate: $275/hour + travel). Parts are available at
list price from the spare parts catalog.

*© 2026 Acme Fab Equipment. For contract enquiries: contracts@acmefab.com*
