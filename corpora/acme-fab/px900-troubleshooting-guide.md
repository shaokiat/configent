# PX-900 Plasma Etcher: Troubleshooting Guide

**Document ID:** PX900-TG-Rev3
**Product:** PX-900 ICP Plasma Etcher
**Revision Date:** April 2026

---

## 1. Introduction

This guide covers common fault conditions, error codes, and diagnostic procedures for the PX-900.
For scheduled maintenance, see the Maintenance Manual (PX900-MM-Rev4). For process chemistry
guidance, contact Acme Process Engineering.

Error codes are displayed on the process controller touchscreen in the format `E-XXX`. All errors
are logged to the event database; retrieve with the command `logview --since <date>` on the
controller terminal.

---

## 2. Error Code Reference

### E-4xx Series: Vacuum and Gas System

| Code | Description | Immediate Action |
|------|-------------|-----------------|
| E-401 | Turbo pump speed low (< 90% nominal) | Check turbo power supply; inspect pump |
| E-403 | Base pressure not reached in timeout | Leak check per MM §4.1 |
| E-411 | Process gas overrun (actual > setpoint + 10%) | Check MFC; recalibrate per MM §5.2 |
| E-415 | Helium backside flow interrupted | Check He supply line and pressure regulator |
| **E-417** | **Helium backside cooling leak detected** | **Immediate chamber vent required** |
| E-419 | Exhaust pressure high | Check exhaust fan and duct obstruction |
| E-422 | Process gas purity alarm | Do not process; contact gas team |

#### E-417 Detail

Error code E-417 indicates a helium backside cooling leak and requires immediate chamber vent.

Helium is used at the wafer–ESC interface to improve thermal coupling between the wafer and the
electrostatic chuck. A confirmed backside He leak means:

1. The He supply path has a breach, most commonly at the ESC lift-pin seal or the He feed
   through the lower electrode.
2. Helium is entering the process chamber, diluting the process gas and altering plasma
   chemistry.
3. Thermal control of the wafer is compromised; runaway temperatures are possible within
   seconds under high-power conditions.

**Immediate response:**

1. The controller will auto-abort the process recipe and extinguish the plasma.
2. Do not override the abort or attempt to restart the recipe.
3. Initiate a controlled vent to nitrogen per MM §4.3.
4. Evacuate non-essential personnel from the process bay.
5. Call Acme Field Service (Tier-1 response line) once the chamber is safely vented.

After venting, perform a helium sniff test on all ESC feedthroughs and lift-pin seals before
returning the tool to service. Replacement part for the ESC lower seal: P/N PX900-ESC-LS1.

### E-5xx Series: RF and Plasma

| Code | Description | Immediate Action |
|------|-------------|-----------------|
| E-501 | RF generator interlock open | Check door interlocks and RF cage |
| E-503 | Reflected power high (> 15% forward) | Matching network calibration per MM §5.1 |
| E-507 | Plasma ignition failure (3 attempts) | Check gas flows, pressure, and electrode |
| E-511 | Bias RF overtemperature | Check cooling water flow to bias generator |
| E-519 | ICP coil current alarm | Inspect ICP coil; check coil gasket PX900-GASKET-C1 |

### E-6xx Series: Temperature and Cooling

| Code | Description | Immediate Action |
|------|-------------|-----------------|
| E-601 | Chiller outlet temperature out of range | Check chiller setpoint; inspect fluid lines |
| E-607 | Chamber wall temperature high | Check facility cooling water; inspect baffles |
| E-613 | ESC temperature sensor fault | Replace ESC temperature sensor; contact Field Service |

---

## 3. Diagnostic Procedures

### 3.1 Plasma Stability Diagnosis

If the process shows etch rate variability > ±3% run-to-run:

1. Check focus ring erosion; replace at > 3 mm gap (P/N: PX900-FOCUS-R3).
2. Verify MFC calibration; recalibrate if any flow deviates > 1% from standard.
3. Run the diagnostic recipe DIAG-01 (Langmuir probe scan); compare electron density and
   ion saturation current against baseline values in Appendix A.
4. If etch uniformity is radially skewed, check ESC clamp voltage calibration (MM §5.3).

### 3.2 Vacuum System Diagnosis

**Symptom: Base pressure > 5 × 10⁻⁷ Torr after overnight pump-down**

1. Verify all gas line VCR caps are seated correctly.
2. Check that the chamber lid O-ring is not damaged (visual inspection).
3. If the 1,200 RF-hour seal replacement interval is due, schedule it before further
   diagnosis — a degraded chamber seal is the most common cause. See MM §2.4.
4. Perform leak check per MM §4.1.

**Symptom: Pressure rises rapidly when throttle valve is closed (> 5 mTorr/min)**

This indicates a significant internal leak or virtual leak (trapped gas pocket).
Contact Acme Field Service for a full inspection.

### 3.3 Etch Rate Diagnosis

| Symptom | Likely Cause | First Check |
|---------|-------------|-------------|
| Rate 10–20% low | Gas flow low or pressure high | MFC calibration |
| Rate high and non-uniform | Focus ring worn | Visual inspect, replace if needed |
| Rate drops after 500 RF hrs | Chamber polymer buildup | In-situ clean recipe W-01 |
| Notching on wafer edge | Bias matching | RF matching calibration MM §5.1 |

---

## 4. Field-Replaceable Units (FRU)

The following parts can be replaced by a trained operator without Acme Field Service attendance:

| Part | P/N | Max interval | Operator skill level |
|------|-----|-------------|---------------------|
| Focus ring | PX900-FOCUS-R3 | 300 RF hrs | Trained operator |
| Upper electrode O-ring | PX900-ORING-U2 | 300 RF hrs | Trained operator |
| Exhaust isolation valve seat | PX900-VALVE-S1 | 1,200 RF hrs | Trained operator |
| He backside inlet filter | PX900-HE-F2 | 600 RF hrs | Trained operator |

Parts requiring Acme Field Service:

- Chamber seal kit (PX900-SEAL-A2) — requires torque wrench and RGA verification
- ESC assembly and lower seal
- RF matching network capacitors
- Turbo pump

---

## 5. Escalation Path

| Urgency | Path |
|---------|------|
| Tool down, production impact | Call Acme Tier-1 Service: 1-800-ACM-SVC1 (24/7) |
| Intermittent issue, low urgency | Submit support ticket at support.acmefab.com |
| Safety incident | Call facility EHS immediately, then Acme Safety Hotline |

For Tier-1 contract response time guarantees, see the Service Contracts FAQ.

---

## 6. Related Documents

- PX-900 Maintenance Manual (PX900-MM-Rev4)
- PX-900 Operations Manual (PX900-OM-Rev6)
- LT-200 Load Lock Operations Manual (LT200-OM-Rev2)
- Spare Parts Catalog (SPC-2026)
- Service Contracts and SLA FAQ

*© 2026 Acme Fab Equipment.*
