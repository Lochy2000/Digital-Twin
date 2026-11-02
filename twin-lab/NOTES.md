# Twin lab: build notes

One entry per step, newest at the bottom. Each says what was done, why, and what to check.

## Every file so far

| File | Step | What it does |
|---|---|---|
| `README.md` | L0 | The plan and the ideas behind it |
| `NOTES.md` | L0 | This file |
| `twinlab/model.py` | L1 | The **interface**: what every model must have (`inputs`, `outputs`, `initial_state`, `step`, `predict`) |
| `twinlab/rc1.py` | L1 | The **1R1C model**, the simple twin |
| `tests/test_rc1.py` | L1 | 8 checks of the 1R1C model against hand-worked answers |
| `demo_l1.py`, `demo_l1.png` | L1 | Runs the model through one day and draws it |
| `twinlab/boptest.py` | L2 | Talks to **BOPTEST** and turns its readings into canonical rows |
| `run_boptest.py` | L2 | The command you run to record a BOPTEST building to CSV |
| `tests/test_boptest.py` | L2 | 5 checks of the BOPTEST code using a fake server (no internet needed) |
| `requirements.txt`, `pytest.ini`, `.gitignore` | L1–L2 | Libraries needed, test settings, files git ignores (`data/`, caches) |

---

## L0 · Folder and plan (1 Nov 2026)

**Done**
- Created `twin-lab/` next to `v0.1/` (not inside it). v0.1 stays exactly as tested in E1–E7. The 10 fixes in `FINDINGS.md` §3 are a separate job, done in place later, with v0.1 tagged in git first so the tested version can always be found.
- Wrote the plan in `README.md` (steps L1–L6, rig track R1–R3, hand-over).

**Decisions**
- **First asset:** one heat/cool unit serving one zone, matching the v0.1 asset model placeholder.
- **Offline first:** CSV in and out, canonical-message shape, no broker. Faster to iterate; same code moves to the `twin-engine` service later.
- **Plant ≠ twin:** plant is 2R2C plus things the twin can't see; twin is 1R1C. Avoids circular validation (RR 1 §7; project principle).
- **Test rig planned alongside:** spec written after L2, so it's driven by what the model needs rather than by whatever hardware is to hand.

**Next:** L1, the model interface and the 1R1C model, with the concepts explained before the code.

---

## L1 · Model interface and the 1R1C model (2 Nov 2026)

**Framing:** the twin lab is a sandbox to see how things work, not the actual version. A basic first version is fine as long as parts can be swapped.

**The interface (`twinlab/model.py`).** Every model has to have:
- `inputs`, `outputs`: lists of names, e.g. `["outside_temp_C", "unit_heat_W"]`. The model says what it needs, so the inputs don't have to be known in advance.
- `initial_state(outputs)`: a starting state from the first readings.
- `step(state, inputs, dt)`: move forward `dt` seconds and return a **new** state. It never edits the old one, so a what-if run can start from a copy of the live state safely.
- `predict(state)`: what the sensors should read.

This matches RR 1 §7 and the FMI co-simulation idea (a model lists its inputs and outputs and is moved forward with a "do step" call). When the modeller's model arrives, a small wrapper with these four things makes it fit.

**The 1R1C model (`twinlab/rc1.py`).** Heat balance `C · dT/dt = (T_out − T)/R + Q`, with Q positive for heating and negative for cooling. Stepped with the exact solution: the zone heads towards a balance temperature `T_out + R·Q` and closes the same fraction of the gap each step, `exp(−dt / RC)`. Being exact means uneven gaps between readings give the right answer (tested: 60 + 7 + 233 s = one 300 s step).

**Placeholder values:** R = 0.005 K/W (the zone loses 200 W per °C of difference), C = 5 MJ/K, so the time constant is about 7 h. Made up for a small zone, not Botanic's unit.

**Demo (`demo_l1.py`):** a winter day, 5 °C outside, unit on at 5 kW from 07:00 to 17:00. The zone falls overnight, climbs while the unit runs, and falls again after 17:00. There is no thermostat, so it overshoots to about 25 °C. Controls come later if they're needed.

**To run** (from `twin-lab`, any Python 3.11+):
```
pip install -r requirements.txt
python -m pytest
python demo_l1.py
```

**What it isn't yet:** there are no sensors, no comparison and no residual. This is the model on its own.

**Next (L2):** a simple fake "plant" producing readings to compare against. Then the loop itself: predict, compare, residual.

---

## L2 · BOPTEST as the plant (2 Nov 2026)

**Change of plan:** instead of writing our own 2R2C plant, L2 uses **BOPTEST**, as the v0.1 build plan (§1a) proposed. It's a detailed building model the twin doesn't share, so the twin can't just be checking itself, and we write far less code.

**What BOPTEST is.** A research tool from IBPSA (open source, BSD) that runs detailed building simulations on a server. You don't install anything to use the public one at `api.boptest.net`. You talk to it with web requests:
1. **select** a test case → it gives back a `testid` for your run;
2. **initialize** → choose the start day; it "warms up" the building for a week first, so it doesn't start from cold;
3. **step** → how many seconds each advance moves (we use 900 s = 15 min);
4. **advance**, repeated → each call moves the building on one step and returns its sensor readings;
5. **stop** → frees your run on the server.

We send no control inputs, so BOPTEST's own thermostat runs the unit. We just watch, as the twin would watch a real site.

**Test case:** `bestest_air`, a single room (6 m × 8 m) with a fan coil unit that heats and cools ([BOPTEST MPC paper](https://arxiv.org/pdf/2301.13447)). That's the closest match to our "one heat/cool unit, one zone".

**How the code is split (`twinlab/boptest.py`):**
- `BoptestClient`: sends the five requests above. It's the only part that uses the internet.
- `check_points()`: makes sure every BOPTEST reading we want exists, and works out each one's unit conversion from BOPTEST's own point list (K → °C, W → kW). If a name is wrong, it stops and tells you to run `--list`.
- `to_rows()`: turns one BOPTEST reply into **canonical-message rows**, the same shape v0.1's gateway publishes. So later, the twin reads BOPTEST data, our own simulator or the test rig in exactly the same way.

**Readings kept** (`POINTS` in `boptest.py`):

| BOPTEST name *(to confirm)* | Our point | Unit |
|---|---|---|
| `zon_reaTRooAir_y` | `unit1.zone_air_temp` | °C |
| `zon_weaSta_reaWeaTDryBul_y` | `weather1.outside_air_temp` | °C |
| `fcu_reaPHea_y` | `unit1.heat_output` | kW |
| `fcu_reaPCoo_y` | `unit1.cool_output` | kW |
| `fcu_reaPFan_y` | `unit1.power` | kW |

`heat_output` and `cool_output` are new, sandbox-only points (heat the unit delivers). They're what the 1R1C model needs as its heat input. They aren't in v0.1's asset model.

**Times:** BOPTEST counts seconds from 1 January of a simulated year. We label it 2026 so it reads as a date (`sensor_time`). `ingest_time` is the real time the row was made. `quality` is always GOOD, because v0.1's validator isn't run here.

**Not checked yet (can't reach BOPTEST from Claude's side):**
1. **The BOPTEST point names** are from memory of the test case. `--list` prints the real ones; fix `POINTS` if they differ.
2. **Whether the heating and cooling powers are heat delivered or electricity used.** `--list` shows each one's description. The model needs heat delivered.
3. **Which sign cooling has** (positive or negative), to see from the first CSV.

**To run** (from `twin-lab`, after `pip install -r requirements.txt`):
```
python -m pytest                 # 13 tests, no internet needed
python run_boptest.py --list     # 1. check the point names
python run_boptest.py            # 2. record 3 days (288 steps) to data/boptest_bestest_air.csv
```

**Next (L3):** the twin loop. Read the CSV, step the 1R1C model with the measured outside temperature and heat input, compare with the measured zone temperature, and plot the residual. R and C are guessed first; fitting them properly comes after.
