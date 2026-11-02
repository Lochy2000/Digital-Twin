# DT-TEO twin lab

**Status:** started 1 November 2026 · **sandbox**: a place to try things and see how they work. Nothing here is the actual version. Basic and simple on purpose, and every part swappable.

The v0.1 pipeline (`../v0.1`) answers *"can we move sensor data reliably?"*. This folder works on the question the feasibility study actually rests on:

> **Can a cheap physics model, fed by a handful of sensors, tell a realistic fault apart from normal variation?**

That is the failure criterion in the feasibility reference (§6.3) and RR 1 (§2, §7, §8). It sits under WP3 and WP5 (45% of project cost) and deliverables D2 and D4. v0.1's experiments also showed why it matters: faults that stay inside the normal range (stuck sensor, step, drift) are caught **0%** of the time by the gateway's checks (`../v0.1/experiments/FINDINGS.md`, E1). Catching those is the residual's job.

Build notes, step by step: [`NOTES.md`](NOTES.md).

---

## What this folder is, and isn't

| Is | Isn't |
|---|---|
| An offline lab: Python modules and notebooks, data in and out as CSV files | A running service. No MQTT, Docker or database inside it |
| A place to compare models, observers and detectors, and measure them | A finished twin engine |
| Built around **one heat/cool unit serving one zone** (the placeholder in `../v0.1/dtteo_asset_model.ttl`) | A model of Botanic's real unit. Its specs aren't known yet, so its values are placeholders and are marked as such |
| Planned alongside a small **physical test rig**, so real data can replace simulated data | A sensor-selection study for SME sites (that's WP4 and the partners' job) |

**Why offline first:** a model test that takes seconds to run in a notebook would take minutes through Docker and the broker. Once a method works here, it moves into v0.1 as the `twin-engine` service. The topics for it are already reserved in `../v0.1/contracts/topics.md` (`dt/v1/twin/...`).

**How it connects to v0.1:** the lab reads and writes CSV in the **canonical message** shape (`site`, `point`, `value`, `unit`, `sensor_time`, `quality`). So the same code can later be fed from the broker or the database without changes.

---

## The ideas, briefly

**RC thermal model.** A thermal model drawn like an electric circuit. A **capacitance** (C, in J/K) is how much heat something stores, like a battery. A **resistance** (R, in K/W) is how hard it is for heat to escape, like a wire that resists current. The simplest version, **1R1C**, is one temperature with one heat store and one path to outside:

```
C · dT/dt = (T_out − T) / R  +  Q_unit  +  Q_other
```

In words: the zone warms when the unit adds heat (`Q_unit` > 0, heating) and cools when heat leaks out to a colder outside or the unit removes heat (`Q_unit` < 0, cooling). `R × C` is the **time constant**, which says how fast the zone settles. A **2R2C** model adds a second store, the building fabric (walls, floor, machines), which heats and cools more slowly than the air. This is the "TiTe" model of [Bacher & Madsen (2011)](https://02417.compute.dtu.dk/material/week13/article-grey-box-models.pdf), the standard reference for choosing grey-box building models.

**Grey-box.** The *shape* of the equation comes from physics. The *numbers* (R, C) are fitted from data, because SME sites rarely have documents that give them (RR 1 §7).

**Deliberate mismatch.** The **plant** (the pretend real world) is 2R2C with noise and heat sources the twin doesn't know about. The **twin** is 1R1C. If both used the same model, the twin would only be checking its own maths (RR 1 §7, "the deliberate mismatch is the point of the exercise").

**Observer.** A model run on inputs alone slowly drifts away from reality. An observer nudges the model's state towards each new measurement, by an amount set by a **gain**. A Luenberger observer uses a fixed gain. A Kalman filter works the gain out from how noisy the sensor and the model are. Kalman filters on RC models are the usual approach in building thermal work, e.g. [Li et al. (2021)](https://investigadores.uandes.cl/en/publications/real-time-thermal-dynamic-analysis-of-a-house-using-rc-models-and/), which RR 1 already cites.

**Residual.** Measured minus predicted. On a healthy system it's small noise around zero. A lasting offset means something has changed. Its shape hints at the cause: a slow drift suggests degradation, a step suggests a failure or control change (RR 1 §4).

**Detector.** Statistics on the residual. EWMA (an exponentially weighted moving average) reacts to small lasting shifts. CUSUM (cumulative sum) adds up small deviations until they cross a limit.

---

## Plan

Each step ends with a check and a short entry in `NOTES.md` before the next one starts.

| Step | What | Check / output |
|---|---|---|
| **L0** | Folder, plan, notes *(this step)* | This README |
| **L1** ✔ | Model interface `step(state, inputs, dt) → state` (RR 1 §7) and the 1R1C twin model. Stepping uses the actual time between readings, not a fixed timer (project decision) | 8 tests against answers worked out by hand; `demo_l1.py` draws a day |
| **L2** | Plant simulator: 2R2C zone, a heat/cool unit with modes, capacity limits and efficiency (COP), outdoor temperature profile, unmeasured gains, sensor noise and rounding. Writes canonical-shape CSV | Plots look physically sensible. A cool-down curve has the expected time constant |
| **L3** | Calibration: fit the 1R1C twin on one period (including an overnight cool-down, RR 1 §7), test on another | MAE and RMSE in kelvin. ASHRAE Guideline 14 NMBE and CV(RMSE), with the note that GL14 was written for whole-building energy |
| **L4** | Observer and residual: open-loop vs Luenberger vs Kalman. Data gaps handled by LIVE / COASTING / STALE | Residual is near-white noise on healthy data. Behaviour during a 2 h data gap |
| **L5** | Fault library and detectors: injected faults with known size and start time; EWMA, CUSUM, Z-score | Detection rate, false alarms per day, time to detect, per fault type and size (feasibility ref §6.3) |
| **L6** | **Detectability study.** Vary sensor noise, sampling interval, which sensors exist and fault size | The smallest fault each setup can detect. This is the evidence for or against the sparse-data premise |
| **R1–R3** | Test rig (parallel track): spec after L2, so it measures what the model needs; build; record real cool-downs | Real data replaces the plant in L3–L5 |
| **Hand-over** | Move the chosen model, observer and detector into v0.1 as the `twin-engine` service | Same results from the broker as from CSV |

**Faults planned for L5** (each linked to a real-world cause):

| Fault | Real-world example | Expected residual shape |
|---|---|---|
| Unit loses capacity | Fouled coil, refrigerant loss | Slow drift |
| Efficiency (COP) drops | Same, seen in electrical power | Drift in energy, not temperature |
| Extra heat loss (R falls) | Door or roller shutter left open | Step |
| Unknown heat source | Machine left running | Step or periodic |
| Sensor stuck, offset or drifting | Failed or badly mounted probe | Flat line, step or drift |
| Schedule mismatch | Unit runs outside production hours | Periodic, linked to the clock |

---

## Folder layout (grows step by step)

```
twin-lab/
├── README.md        this plan
├── NOTES.md         build notes, one entry per step
├── demo_l1.py       runs the 1R1C model through one day and draws it
├── twinlab/         Python package: model.py (interface), rc1.py (1R1C) ...
├── notebooks/       experiments that use the package and draw the figures (from L2)
├── tests/           pytest                                                (from L1)
├── data/            generated CSV, git-ignored except small samples       (from L2)
└── rig/             test-rig spec, wiring, firmware notes                 (R1)
```

**Tools (proposed):** Python with NumPy, SciPy (fitting), pandas, matplotlib, and [python-control](https://python-control.org) (BSD-3; observer gains). Jupyter for the notebooks, pytest for tests. All open source and commercially usable, as v0.1 requires.

---

## Open questions

- **Botanic's unit:** heating and cooling capacity, modes, how it is controlled, and whether it can report its own heat output. Until known, the plant uses placeholder values.
- **What the twin's heat input is:** an SME site rarely meters *heat* output, but *electrical* power is cheap to measure (smart plug, clamp meter). If the twin only gets electrical power, efficiency (COP) becomes one more value to fit, and a fall in COP becomes a fault it can see. L2 and L3 will try both.
- **Simulink model and its R/C values** (external dependency): still unknown. The interface in L1 lets it be plugged in later as one more model.
- **Thermal camera and the ML PC:** not in the architecture yet. A likely later use is spotting where heat leaks (R) or confirming a fault. Kept out of scope here for now.

---

## Sources

- Bacher, P. and Madsen, H. (2011). Identifying suitable models for the heat dynamics of buildings. *Energy and Buildings*, 43, 1511–1522. [PDF](https://02417.compute.dtu.dk/material/week13/article-grey-box-models.pdf)
- Li, Y., Castiglione, J., Astroza, R. and Chen, Y. (2021). Real-time thermal dynamic analysis of a house using RC models and joint state-parameter estimation. *Building and Environment*, 188, 107184. [Record](https://investigadores.uandes.cl/en/publications/real-time-thermal-dynamic-analysis-of-a-house-using-rc-models-and/)
- Project: RR 1 (§2, §4, §7, §8), DT-TEO feasibility reference (§5, §6), v0.1 build plan (§1e, §3, §4e), `../v0.1/experiments/FINDINGS.md`.
