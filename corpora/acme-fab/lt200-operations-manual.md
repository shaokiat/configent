# LT-200 Load Lock: Operations Manual

**Document ID:** LT200-OM-Rev2
**Product:** LT-200 Wafer Load Lock System
**Revision Date:** January 2026
**Compatible with:** PX-900 cluster tool configurations LT200-C1 and LT200-C2

---

## 1. Overview

The LT-200 is a single-wafer, nitrogen-purged load lock for 300 mm wafer transfer between
atmospheric cassette storage and the PX-900 process chamber. It features:

- Independent rough pump and high-vacuum pump (shared with PX-900 main chamber)
- Nitrogen backfill for atmospheric breaks (prevents O₂/moisture ingress)
- Automated EFEM (Equipment Front End Module) interface for cassette-to-load-lock transfer
- Temperature-controlled stage for wafer pre-conditioning (20–80°C range)

---

## 2. Operating Procedures

### 2.1 Startup Sequence

1. Verify that both the LT-200 rough pump and the facility N₂ supply are operational.
2. On the cluster tool controller, select **LT-200 > Initialize**.
3. The load lock will pump down to < 1 × 10⁻³ Torr (rough vacuum) automatically.
4. Once rough vacuum is achieved, the gate valve to the PX-900 process chamber can be opened.
5. Confirm load lock temperature on the stage heater display; setpoint for idle standby is
   45°C.

### 2.2 Idle Standby Configuration

The recommended idle standby temperature for the LT-200 load lock is 45 degrees Celsius.

This temperature is optimised to:

- Prevent moisture condensation on the wafer stage during atmospheric breaks.
- Reduce thermal shock when transferring wafers from ambient cassette storage.
- Maintain the O-ring seals at a temperature where outgassing is minimised.

Do not set the idle standby temperature below 35°C or above 55°C without consulting Acme
Process Engineering. Below 35°C, moisture adsorption on the stage can increase base pressure
in the PX-900 by an order of magnitude. Above 55°C, edge exclusion rings may warp.

### 2.3 Wafer Load Procedure

1. Confirm gate valve between LT-200 and PX-900 is closed.
2. Vent LT-200 to N₂ (load lock controller: **Vent > N₂ Backfill**). Wait for pressure
   equalisation signal (green LED on EFEM panel).
3. Open the EFEM door; robot arm transfers wafer from cassette to LT-200 stage.
4. Close EFEM door.
5. Pump LT-200 to rough vacuum (< 1 × 10⁻³ Torr) — typically 45–90 seconds.
6. Open gate valve to PX-900 transfer chamber.
7. Transfer wafer to PX-900 process chamber via transfer robot.

### 2.4 Wafer Unload Procedure

Reverse of §2.3. Ensure PX-900 recipe is complete and wafer has cooled to < 50°C
(monitored by stage pyrometer) before opening the gate valve for unload.

---

## 3. Temperature Control

### 3.1 Stage Heater Setpoints

| Operating Mode | Stage Temperature | Purpose |
|---------------|------------------|---------|
| Idle standby | 45°C | Moisture prevention, O-ring conditioning |
| Pre-heat mode | 60°C | Wafer pre-conditioning before high-temperature etch |
| Cool-down | 25°C | After high-power process; wafer transport to metrology |

### 3.2 Temperature Alarms

| Alarm | Setpoint | Action |
|-------|---------|--------|
| Stage overtemperature | 85°C | Emergency vent; check heater control loop |
| Stage undertemperature | 15°C | Check chiller supply; do not load wafers |
| Heater sensor fault | — | Replace stage heater thermocouple |

---

## 4. Maintenance

### 4.1 Daily Checks

- Verify stage temperature is at idle standby setpoint (45°C ± 2°C).
- Check N₂ backfill flow rate: 5–8 slpm during backfill cycle.
- Inspect EFEM door seal: no visible damage or compression set.

### 4.2 Quarterly Maintenance

- Replace EFEM door O-ring (P/N: LT200-ORING-D1).
- Replace load lock gate valve O-ring (P/N: LT200-ORING-GV2).
- Clean stage surface with IPA; inspect for scratches or particle accumulation.
- Replace LT-200 rough pump exhaust filter (P/N: LT200-FILTER-E1).

---

## 5. Interface with PX-900

The LT-200 communicates with the PX-900 cluster controller via RS-485. Key interlocks:

| Interlock | Condition | Effect |
|-----------|-----------|--------|
| LT-200 pressure high | > 1 × 10⁻² Torr when gate open | Gate valve closes; PX-900 process abort |
| Stage temperature alarm | Outside 20–80°C | Wafer transfer inhibited |
| EFEM door sensor | Door open during pump-down | Pump-down inhibited; error logged |

For PX-900 error codes related to load lock interface, see the PX-900 Troubleshooting Guide
(PX900-TG-Rev3), E-4xx series.

---

## 6. Spare Parts

| Part | P/N | Interval |
|------|-----|----------|
| EFEM door O-ring | LT200-ORING-D1 | Quarterly |
| Gate valve O-ring | LT200-ORING-GV2 | Quarterly |
| Rough pump exhaust filter | LT200-FILTER-E1 | Quarterly |
| LT-200 valve actuator | LT200-VALVE-B1 | On failure / 2 years |
| Stage heater assembly | LT200-HEATER-S3 | On failure |

See the Acme Spare Parts Catalog (SPC-2026) for pricing and lead times. Part LT200-VALVE-B1
can be quoted via the customer portal.

---

## 7. Related Documents

- PX-900 Maintenance Manual (PX900-MM-Rev4)
- PX-900 Troubleshooting Guide (PX900-TG-Rev3)
- Acme Spare Parts Catalog (SPC-2026)
- Service Contracts and SLA FAQ

*© 2026 Acme Fab Equipment.*
