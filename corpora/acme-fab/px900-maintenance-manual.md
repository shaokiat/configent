# PX-900 Plasma Etcher: Maintenance Manual

**Document ID:** PX900-MM-Rev4
**Product:** PX-900 Inductively Coupled Plasma (ICP) Etcher
**Revision Date:** March 2026
**Applies to:** Serial numbers PX900-2200 and later

---

## 1. Overview

The PX-900 is a 300 mm wafer plasma etcher designed for high-volume silicon, dielectric, and metal
etch processes. It uses an inductively coupled plasma (ICP) source operating at 13.56 MHz with a
bias power supply for directional etch control.

This manual covers routine preventive maintenance schedules, component replacement procedures, and
safety precautions. It should be read alongside the PX-900 Operations Manual (PX900-OM-Rev6) and
the Troubleshooting Guide (PX900-TG-Rev3).

---

## 2. Preventive Maintenance Schedule

### 2.1 Daily Checks (every shift)

| Item | Check | Action if Failed |
|------|-------|-----------------|
| Chamber pressure baseline | < 1 × 10⁻⁷ Torr (idle) | Leak check procedure §4.1 |
| ESC clamp voltage | Within ±2% of setpoint | Recalibrate per §5.3 |
| Helium backside cooling flow | 8–12 sccm at nominal wafer temp | See troubleshooting guide |
| RF forward/reflected power ratio | Reflected < 2% of forward | Check matching network §5.1 |
| Process gas purity indicators | Green on all lines | Do not process; notify gas team |

### 2.2 Weekly Checks

- Inspect chamber walls for polymer buildup. Clean with in-situ plasma clean (O₂/CF₄ recipe W-01)
  if deposit thickness exceeds 50 μm as measured by QCM.
- Check all gas line fittings with leak detector solution; zero permitted.
- Verify exhaust pump oil level and colour (should be clear amber, not black).
- Inspect focus ring for erosion; replace if gap > 3 mm.

### 2.3 Quarterly Checks (every 300 RF hours)

- Replace focus ring (P/N: PX900-FOCUS-R3).
- Replace upper electrode O-ring (P/N: PX900-ORING-U2).
- Full chamber vent and wet clean per §4.2.
- Calibrate mass flow controllers per §5.2.

### 2.4 Annual / 1,200 RF-Hour Service

The PX-900 plasma etcher requires chamber seal replacement every 1,200 RF hours.

This is the most critical scheduled maintenance item. The chamber seal (P/N: PX900-SEAL-A2,
description: chamber seal kit, fluoroelastomer) degrades under sustained plasma exposure and
elevated temperatures. Failure to replace on schedule leads to:

- Gradual loss of base vacuum (vacuum creep of > 0.5 mTorr/minute indicates seal compromise).
- Risk of process contamination from atmospheric oxygen and moisture ingress.
- Potential catastrophic chamber breach under high-power process conditions.

**Procedure summary:**

1. Complete a full 8-hour pump-down cycle to verify current seal integrity before scheduling
   the replacement window.
2. Vent chamber to nitrogen (never to air) per §4.3.
3. Torque-down sequence: lower electrode bolts first, counterclockwise from bolt #1 (marked),
   then upper lid bolts. Torque specification: 18 N·m ± 0.5 N·m.
4. Pump down to < 5 × 10⁻⁷ Torr before reintroducing process gases.
5. Run seal-verification recipe V-01 (10 min O₂ plasma at 500 W) and confirm no leak via RGA.

> **Note:** PX900-SEAL-A2 must be sourced from Acme Fab or an Acme-approved distributor.
> Third-party seals void the chamber warranty and are not rated for the fluorine chemistry
> used in silicon nitride etch processes.

---

## 3. Component Replacement Reference

| Component | Part Number | Replacement Interval | Torque Spec |
|-----------|-------------|---------------------|-------------|
| Chamber seal kit | PX900-SEAL-A2 | Every 1,200 RF hours | 18 N·m ±0.5 |
| Focus ring | PX900-FOCUS-R3 | Every 300 RF hours | 6 N·m ±0.2 |
| Upper electrode O-ring | PX900-ORING-U2 | Every 300 RF hours | Hand-tight + ¼ turn |
| ICP coil gasket | PX900-GASKET-C1 | Every 2,400 RF hours | 12 N·m ±0.5 |
| ESC clamp plate | PX900-ESC-P4 | On failure / 5 years | 10 N·m ±0.5 |
| Exhaust isolation valve seat | PX900-VALVE-S1 | Every 1,200 RF hours | — |

For spare parts pricing and availability, see the Acme Spare Parts Catalog or contact your
regional field service representative. Part PX900-SEAL-A2 can also be quoted via the customer
portal using the `pricing_lookup` tool.

---

## 4. Chamber Procedures

### 4.1 Leak Check Procedure

1. Isolate all process gas lines at the VCR fittings upstream of the gas panel.
2. Close the throttle valve and rough valve; isolate the turbo pump.
3. Back-fill to 10 Torr with nitrogen.
4. Wait 10 minutes. Measure pressure rise rate. Acceptable: < 0.05 Torr/min.
5. If leak rate exceeds limit, perform helium sniff test around all chamber flanges and
   feedthroughs.

### 4.2 Full Wet Clean

> **Warning:** Wear nitrile gloves, face shield, and chemical apron. The chamber interior
> surfaces will have fluorocarbon polymer deposits that are irritants.

1. Vent chamber per §4.3.
2. Remove upper lid (6 × M10 bolts, counterclockwise from bolt #1).
3. Wipe chamber walls with IPA-soaked lint-free cloth. Do not use abrasive pads.
4. Rinse with DI water; dry with N₂ gun.
5. Reinstall lid; torque per §3 table.
6. Pump to base pressure; verify < 1 × 10⁻⁷ Torr before proceeding.

### 4.3 Controlled Vent to Nitrogen

1. Stop all process gas flows.
2. Run plasma clean recipe C-01 (5 min CF₄/O₂) to clear residual fluorine from chamber.
3. Close throttle valve.
4. Open N₂ backfill valve (1 slpm); allow chamber to rise to atmosphere slowly (> 5 minutes).
5. Do not vent to air: moisture and oxygen contamination requires additional bake-out.

---

## 5. Calibration Procedures

### 5.1 RF Matching Network Calibration

The matching network auto-tunes during plasma ignition. Manual calibration is required if
reflected power consistently exceeds 5% of forward power after auto-tune:

1. Load capacitor C1: adjust in 0.5 pF increments while monitoring reflected power display.
2. Series capacitor C2: adjust after C1 to minimize reflected power to < 1%.
3. Record final C1 and C2 values in the maintenance log.

### 5.2 Mass Flow Controller Calibration

MFC calibration uses an external NIST-traceable flow standard. Perform with the chamber at
atmosphere and all process gas lines flushed with N₂.

1. Connect calibration standard to MFC outlet.
2. Command 50% full-scale flow via the process controller.
3. Record displayed versus measured flow; adjust span if deviation > 1%.
4. Repeat at 25% and 75% full-scale.

### 5.3 ESC Clamp Voltage Calibration

1. Place a bare silicon wafer on the ESC.
2. Apply clamp voltage per process recipe setpoint.
3. Measure wafer temperature with IR pyrometer at 5 points; deviation from setpoint should be
   < ±2°C at steady state.
4. Adjust ESC voltage in 50 V increments if deviation exceeds ±2°C.

---

## 6. Safety

- **High voltage:** RF generator output and matching network contain lethal voltages. De-energize
  and lock out before opening any RF enclosure.
- **Toxic gases:** Always purge lines with N₂ after ending fluorine-bearing processes. Verify
  gas cabinet interlock before entering the process bay.
- **Cryogenic hazard:** The turbomolecular pump bearing lubrication may contain cryogenic fluids.
  Follow the pump manufacturer's SDS.

For emergency procedures, see the site EHS manual. In the event of a catastrophic chamber
failure, activate the facility exhaust system and evacuate the bay before calling Acme Field
Service at the 24-hour emergency line.

---

## 7. Related Documents

- PX-900 Operations Manual (PX900-OM-Rev6)
- PX-900 Troubleshooting Guide (PX900-TG-Rev3)
- LT-200 Load Lock Operations Manual (LT200-OM-Rev2)
- Acme Spare Parts Catalog (SPC-2026)
- Service Contracts and SLA FAQ

*© 2026 Acme Fab Equipment. All rights reserved. Reproduction for internal use permitted.*
