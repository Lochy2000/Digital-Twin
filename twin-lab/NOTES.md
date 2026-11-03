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
| `plot_plant.py` | L2 | Draws a recorded CSV (temperatures, heating/cooling, sunshine) to a PNG |
| `data/boptest_bestest_air.csv` | L2 | **The first recording**: 3 days, 15–17 Jan, 288 steps × 8 points = 2,304 rows (git-ignored; re-record with `run_boptest.py`) |
| `tests/test_boptest.py` | L2 | 5 checks of the BOPTEST code using a fake server that mimics the real point list (no internet needed) |
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

**Readings kept** (`POINTS` in `boptest.py`, names confirmed with `--list`, see below):

| BOPTEST name | BOPTEST's description | Our point | Unit |
|---|---|---|---|
| `zon_reaTRooAir_y` | Zone air temperature | `unit1.zone_air_temp` | °C |
| `zon_weaSta_reaWeaTDryBul_y` | Outside drybulb temperature | `weather1.outside_air_temp` | °C |
| `fcu_reaPHea_y` | Heating **thermal** power | `unit1.heat_output` | kW |
| `fcu_reaPCoo_y` | Cooling **electrical** power | `unit1.cool_power` | kW |
| `fcu_reaPFan_y` | Supply fan electrical power | `unit1.power` | kW |
| `zon_reaPLig_y` | Lighting power | `zone1.lighting_power` | kW |
| `zon_reaPPlu_y` | Plug load power | `zone1.plug_power` | kW |
| `zon_weaSta_reaWeaHGloHor_y` | Sunshine on a flat surface | `weather1.solar_global` | W/m² |

Points not in v0.1's asset model are sandbox-only for now.

**Times:** BOPTEST counts seconds from 1 January of a simulated year. We label it 2026 so it reads as a date (`sensor_time`). `ingest_time` is the real time the row was made. `quality` is always GOOD, because v0.1's validator isn't run here.

### Getting it running (2 Nov 2026)

1. **The public server failed.** `api.boptest.net` had an expired security certificate, and its simulation workers weren't starting (`select` hung for 5+ minutes). The version and test-case list still answered, so it was their side, not our code. We didn't switch off certificate checking to get round it.
2. **Ran BOPTEST locally instead:** clone `ibpsa/project1-boptest`, check out `v0.9.0`, run `docker compose up web worker provision`. It's the same API on your own PC. It answers on **port 8000**, not 80, so use `--url http://127.0.0.1:8000`. `provision` exits with code 0 once it has loaded the 12 test cases; that's normal.
3. **`--list` worked**, and all 5 original point names were right.
4. **Bug found and fixed (took two goes):** the local BOPTEST answers `stop` with plain text, not JSON, and `_call()` crashed trying to read it as JSON. My first fix assumed the reply was *empty*, which was wrong, and the crash came back on the recording run. Now `_call()` returns the reply as plain text whenever it isn't JSON. `run_boptest.py` also treats a failed `stop` as a warning, since the data is already saved by then. A test covers the plain-text reply.
5. **First recording saved:** `data/boptest_bestest_air.csv`, 3 days, 2,304 rows, every value in a sensible range.

### What the first recording shows

Chart: `python plot_plant.py` (saves `data/boptest_bestest_air.png`).

| Point | Min | Max | Mean |
|---|---|---|---|
| Zone temperature | 15.0 °C | 24.3 °C | 19.9 °C |
| Outside temperature | −12.9 °C | 6.7 °C | −3.5 °C |
| Heating, heat delivered | 0 | 2.76 kW | 0.26 kW |
| Cooling, electricity used | 0 | 0.58 kW | 0.06 kW |
| Sunshine | 0 | 525 W/m² | 124 W/m² |

**A daily pattern, set by BOPTEST's own thermostat** (read from the chart, not from BOPTEST's documentation):
- **Night:** the zone is held at about **15 °C**. Heating rises as it gets colder outside.
- **Around 07:00–08:00:** the setpoint jumps to about **21 °C**, with a short burst of heating (up to 2.8 kW).
- **Midday:** the sun pushes the room up to about **24 °C**, and **cooling switches on, even in January**. This room has large windows, so sunshine is one of its biggest heat inputs.
- **Evening:** heating and cooling are both off, and the zone **drifts down from 24 °C to 15 °C over several hours**.

**What it means for the twin:**
1. **My assumption was wrong:** cooling isn't off in January. Cooling is only measured as electricity used, so during those hours the twin doesn't know the full heat flow. **Resolved (3 Nov):** BOPTEST's own documentation gives the chiller COP as a constant 3.0, so heat removed = 3 × cooling electricity (see "What bestest_air actually is").
2. **Sunshine matters a lot.** A 1R1C model without it will show a big residual every sunny midday. That's expected, not a fault, and the first test of "does adding sunshine as an input make the twin better?".
3. **The evening drift is a free cool-down,** exactly the calibration method in RR 1 §7. Each evening of this recording can be used to fit R and C.

### What `--list` taught us

- **Heating is measured as heat delivered** (thermal), which is what the 1R1C model needs.
- **Cooling is only measured as electricity used**, not heat removed. Heat removed = electricity × the chiller's efficiency (COP). The point was renamed `cool_power`, not `cool_output`, to stay honest. (The COP turned out to be documented as 3.0; see below.)
- **Free extras recorded:** lighting, plug loads and sunshine all heat the room, but the 1R1C model doesn't include them yet. Recording them costs nothing and lets L3 test "does adding them make the twin better?".

**To run** (from `twin-lab`, after `pip install -r requirements.txt`, with BOPTEST running in Docker):
```
python -m pytest                                               # 13 tests, no internet needed
python run_boptest.py --list --url http://127.0.0.1:8000       # check the point names
python run_boptest.py --url http://127.0.0.1:8000              # record 3 days from 15 Jan to data/boptest_bestest_air.csv
```
The default is 15 January. (I'd expected cooling to be off then; the recording showed it isn't, see below.)

**Next (L3):** the twin loop. Read the CSV, step the 1R1C model with the measured outside temperature and heat input, compare with the measured zone temperature, and plot the residual. R and C are guessed first; fitting them properly comes after.

### What `bestest_air` actually is (from its own docs, 3 Nov 2026)

Source: `../boptest/testcases/bestest_air/doc/index.html` in the local BOPTEST copy.

| | |
|---|---|
| Building | One room, 6 m × 8 m × 2.7 m, two-person office. Concrete block walls with insulation, concrete floor slab. Two south-facing windows, each 3 m × 2 m (why the sun heats it so much) |
| Climate | **Denver, Colorado, USA** (a "typical year" weather file, `DRYCOLD.mos`). Built into the compiled model |
| Heating and cooling | Fan coil unit: hot water from a gas boiler (efficiency 0.9), chilled water from a chiller with **COP fixed at 3.0** |
| Thermostat | 21 °C heating and 24 °C cooling from 08:00 to 18:00; 15 °C and 30 °C otherwise. This matches what the chart showed |
| What we can change without rebuilding | Start day (any day of the year), step size, the setpoints, supply air temperature and fan speed (overrides), price scenarios |
| What needs a rebuild | The building, the equipment and the **weather/location**. Changing the weather means swapping the weather file and recompiling the model with BOPTEST's build tools. Possible, not worth it now |

**Why it's still useful from the UK.** The twin learns R and C from the data of whatever it's watching, so it isn't tied to a location. BOPTEST lets us test the *method*: can a simple 1R1C model follow a detailed building it didn't design, and does the residual catch faults? Denver's weather changes the numbers (colder nights, much more sun than London) but not whether the method works. A sunny, swinging climate is arguably a harder test.

**What not to use it for.** Quoting kWh, costs or savings as if they were UK figures; claims about SME process heat; anything about Botanic's own unit. Representative UK numbers would need UK weather: either a rebuilt BOPTEST model with a London weather file, or our own simple plant driven by real UK weather data. Both are later options.
