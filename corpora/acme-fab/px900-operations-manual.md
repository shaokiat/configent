# PX-900 Plasma Etcher: Operations Manual

**Document ID:** PX900-OM-Rev6
**Product:** PX-900 ICP Plasma Etcher
**Revision Date:** May 2026

---

## 1. Introduction

This manual describes daily operating procedures for the PX-900. It assumes the tool has been
installed and qualified by Acme Field Service. For maintenance procedures, see PX900-MM-Rev4.
For fault diagnosis, see PX900-TG-Rev3.

---

## 2. Tool Overview

The PX-900 processes 300 mm silicon wafers using inductively coupled plasma (ICP) etching.
Key process parameters:

| Parameter | Range | Typical |
|-----------|-------|---------|
| Chamber pressure | 1–200 mTorr | 10–50 mTorr |
| ICP power | 200–3000 W | 1500 W |
| Bias RF power | 0–1000 W | 200 W |
| Process temperature | 20–80°C | 40°C |
| Helium backside pressure | 4–20 Torr | 10 Torr |

---

## 3. Daily Startup

1. Log in to the process controller with your operator credentials.
2. Navigate to **Tool Status > Initialize**.
3. The automated startup sequence runs (approximately 8 minutes):
   - Turbomolecular pump spin-up
   - Helium backside system self-test
   - RF system interlock verification
   - Chiller temperature stabilisation
4. Confirm green status on all subsystems before loading wafers.
5. If any subsystem shows yellow or red, refer to PX900-TG-Rev3 for the relevant error code.

---

## 4. Loading a Wafer

1. Confirm LT-200 load lock is at idle standby temperature (45°C) and rough vacuum.
2. Place 300 mm wafer cassette on EFEM port 1 (front-left).
3. On the controller, navigate to **Wafer Transfer > Load from Cassette**.
4. Select cassette slot and target process chamber.
5. The robot arm transfers the wafer automatically; confirm wafer present signal on the
   controller before proceeding.
6. Do not open the EFEM door during an automated transfer sequence.

---

## 5. Running a Process Recipe

1. On the controller, navigate to **Process > Select Recipe**.
2. Choose from the qualified recipe library (contact Process Engineering for access to
   recipe editing).
3. Confirm all process parameters match the recipe spec sheet before running.
4. Select **Run**; the tool will:
   - Open the gate valve to the process chamber
   - Transfer the wafer from load lock
   - Begin the plasma process
5. Monitor the process on the **Live Process** screen; check ICP power, bias power, and He
   backside flow for anomalies.
6. On process complete, the wafer returns to the load lock automatically for cool-down.

---

## 6. End of Shift Procedure

1. Confirm no wafers are in-process or in-transit.
2. Run the in-situ chamber clean recipe C-01 if the shift ran > 20 wafers or any residue
   was visible on the electrode.
3. Log the tool's RF-hour counter value in the maintenance log (controller: **Logs > RF Hours**).
4. Return to idle standby state; do not power down the turbo pump unless directed.

---

## 7. Process Gases Commonly Used on PX-900

| Process | Gases | Typical Conditions |
|---------|-------|--------------------|
| Silicon etch | SF₆/O₂ | 30 mTorr, 1500 W ICP, 200 W bias |
| Silicon nitride etch | CF₄/CHF₃ | 20 mTorr, 1200 W ICP, 150 W bias |
| Oxide etch | C₄F₈/Ar | 15 mTorr, 1800 W ICP, 300 W bias |
| Metal etch (Al/Ti) | Cl₂/BCl₃ | 10 mTorr, 1000 W ICP, 250 W bias |
| Chamber clean | O₂/CF₄ | 50 mTorr, 500 W ICP, no bias |

> **Safety:** Chlorine and fluorine chemistries are toxic. Verify exhaust treatment system
> is operational before starting any halogen-containing process.

---

## 8. Qualification and Process Change Control

New recipes must be qualified per the Acme Recipe Qualification Protocol (RQP-01) before
production use:

1. 5-wafer qualification run on dummy wafers
2. Cross-wafer uniformity measurement (< ±3% target)
3. Repeatability check (3 consecutive runs, SPC within ±1σ)
4. Sign-off by Process Engineering and Quality

Contact processengineering@acmefab.com to request recipe support.

---

## 9. Related Documents

- PX-900 Maintenance Manual (PX900-MM-Rev4)
- PX-900 Troubleshooting Guide (PX900-TG-Rev3)
- LT-200 Operations Manual (LT200-OM-Rev2)
- Service Contracts and SLA FAQ (SC-FAQ-Rev5)

*© 2026 Acme Fab Equipment.*
