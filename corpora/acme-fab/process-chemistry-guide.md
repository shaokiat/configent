# PX-900 Process Chemistry Guide

**Document ID:** PX900-PCG-Rev1
**Revision Date:** February 2026

---

## 1. Overview

This guide covers the process gas chemistries qualified for use on the PX-900. It is intended
for process engineers designing and qualifying etch recipes. Operators should not modify gas
flow or chemistry parameters without a qualified recipe change request.

---

## 2. Silicon Etch

### 2.1 Isotropic Silicon Etch (SF₆/O₂)

Isotropic etch is used for bulk removal where profile control is not critical.

| Parameter | Range | Starting Point |
|-----------|-------|---------------|
| SF₆ flow | 50–200 sccm | 100 sccm |
| O₂ flow | 5–20 sccm | 10 sccm |
| Chamber pressure | 20–100 mTorr | 50 mTorr |
| ICP power | 500–2000 W | 1000 W |
| Bias RF power | 0–100 W | 0 W (isotropic) |

Etch rate: 1–5 μm/min depending on conditions. Selectivity to SiO₂: ~20:1 at baseline.

### 2.2 Anisotropic Silicon Etch (Bosch Process, SF₆/C₄F₈)

Deep reactive ion etching (DRIE) for high-aspect-ratio structures. Uses alternating etch
(SF₆) and passivation (C₄F₈) steps.

| Parameter | Etch Step | Passivation Step |
|-----------|-----------|-----------------|
| SF₆ flow | 200 sccm | 0 sccm |
| C₄F₈ flow | 0 sccm | 150 sccm |
| Pressure | 30 mTorr | 30 mTorr |
| ICP power | 2000 W | 1000 W |
| Step duration | 7 s | 5 s |

Achievable aspect ratios: up to 30:1 for standard DRIE; up to 50:1 with cryogenic assist
(requires LT-200 with cooling option).

---

## 3. Dielectric Etch

### 3.1 Silicon Dioxide (C₄F₈/Ar or CHF₃/CF₄)

| Parameter | C₄F₈/Ar | CHF₃/CF₄ |
|-----------|---------|---------|
| Pressure | 15 mTorr | 20 mTorr |
| ICP power | 1800 W | 1200 W |
| Bias power | 300 W | 200 W |
| Si selectivity | ~10:1 | ~8:1 |

### 3.2 Silicon Nitride (CF₄/CHF₃)

Silicon nitride etch is the most common application on the PX-900 in logic fabs. The
chamber seal kit PX900-SEAL-A2 is specifically rated for sustained fluorine exposure, making
it the required part for tools running significant nitride etch workloads.

| Parameter | Range | Typical |
|-----------|-------|---------|
| CF₄ flow | 30–80 sccm | 50 sccm |
| CHF₃ flow | 20–60 sccm | 30 sccm |
| Pressure | 15–30 mTorr | 20 mTorr |
| ICP power | 800–1500 W | 1200 W |
| Bias power | 100–300 W | 150 W |

---

## 4. Metal Etch

### 4.1 Aluminium and Titanium (Cl₂/BCl₃)

> **Safety warning:** Chlorine and BCl₃ are toxic. Verify that the exhaust abatement system
> is online and the gas cabinet interlock is active before initiating any chlorine-containing
> process.

| Parameter | Al etch | Ti etch |
|-----------|---------|---------|
| Cl₂ flow | 80 sccm | 40 sccm |
| BCl₃ flow | 40 sccm | 20 sccm |
| Pressure | 8–15 mTorr | 5–10 mTorr |
| ICP power | 800–1200 W | 600–1000 W |

After any Cl-based process, run the Cl purge recipe P-CL (N₂/Ar purge, 5 min, no plasma)
before venting the chamber. This prevents hydrochloric acid formation on atmosphere exposure.

---

## 5. Chamber Conditioning

### 5.1 Pre-Process Conditioning

Before starting production lots, run 5 conditioning wafers (bare silicon or dummy) to
stabilise the chamber walls and ensure repeatable process conditions.

### 5.2 Chamber Clean Recipes

| Recipe | Chemistry | Duration | Use case |
|--------|-----------|----------|---------|
| C-01 | O₂/CF₄ | 10 min | Daily clean, post-Si and dielectric |
| C-02 | O₂ only | 15 min | Post-photoresist strip |
| P-CL | N₂/Ar purge | 5 min | Post-Cl₂ metal etch (mandatory) |
| W-01 | O₂/CF₄ high power | 20 min | Weekly deep clean |

---

## 6. Related Documents

- PX-900 Operations Manual (PX900-OM-Rev6)
- PX-900 Maintenance Manual (PX900-MM-Rev4)
- Spare Parts Catalog (SPC-2026)

*© 2026 Acme Fab Equipment.*
