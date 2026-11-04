# Twin lab: build notes

One entry per step, newest at the bottom. Each says what was done, why, and what to check.

## Every file so far

| File | Step | What it does |
|---|---|---|
| `README.md` | L0 | The plan and the ideas behind it |
| `NOTES.md` | L0 | This file |
| `twinlab/model.py` | L1 | The **interface**: what every model must have (`inputs`, `outputs`, `initial_state`, `step`, `predict`) |
| `twinlab/rc1.py` | L1, L3c | The **1R1C model**, the simple twin. L3c added internal gains and sunshine as inputs |
| `tests/test_rc1.py` | L1 | 8 checks of the 1R1C model against hand-worked answers |
| `demo_l1.py`, `demo_l1.png` | L1 | Runs the model through one day and draws it |
| `twinlab/boptest.py` | L2 | Talks to **BOPTEST** and turns its readings into canonical rows |
| `run_boptest.py` | L2 | The command you run to record a BOPTEST building to CSV |
| `plot_plant.py` | L2 | Draws a recorded CSV (temperatures, heating/cooling, sunshine) to a PNG |
| `data/boptest_bestest_air.csv` | L2 | **The first recording**: 3 days, 15–17 Jan, 288 steps × 8 points = 2,304 rows (git-ignored; re-record with `run_boptest.py`) |
| `tests/test_boptest.py` | L2 | 5 checks of the BOPTEST code using a fake server that mimics the real point list (no internet needed) |
| `twinlab/data.py` | L3a | Reads a canonical CSV into one dict per moment in time |
| `tests/test_data.py` | L3a | 1 check that rows are grouped by time and sorted |
| `look_l3a.py` | L3a | Prints the first few moments as a table: what the twin will "see" |
| `twinlab/loop.py` | L3b | The **twin loop**, open-loop version: steps a model through a recording and returns its predictions |
| `tests/test_loop.py` | L3b | 4 checks: net heat, input names, one prediction per moment, matches stepping by hand |
| `run_l3b.py` | L3b | Runs the 1R1C twin through the recording; prints measured vs predicted every 3 h |
| `explore_l3b_gains.py` | L3b | The experiment showing *why* the twin drifts: missing heat sources |
| `twinlab/metrics.py` | L3c | Residual (measured − predicted), MAE and RMSE |
| `tests/test_metrics.py` | L3c | 3 checks with numbers worked out by hand |
| `run_l3c.py`, `l3c_twin_vs_plant.png` | L3c | Runs the twin with all heat sources; draws measured vs predicted and the residual |
| `twinlab/fit.py` | L3d | **Fits** R, C and sun area to a recording (least squares, SciPy) |
| `tests/test_fit.py` | L3d, L3e | 4 checks: finds known values from wrong guesses; keeps fixed values fixed; several segments; fixed R × C |
| `run_l3d.py`, `l3d_fitted.png` | L3d | Fits on days 1–2, checks on day 3 (unseen); prints and draws the result |
| `data/boptest_14days.csv` | L3e | **Second recording**: 14 days, 15–28 Jan, 1,344 moments (git-ignored) |
| `twinlab/data.py` (added to) | L3e | `split_days()` splits a recording into days; `find_cooldowns()` finds stretches with unit off and no sun |
| `twinlab/fit.py` (added to) | L3e | Fits over several separate segments; can fit only some values (`fit=`) or fix R × C (`tau_s=`) |
| `run_l3e.py`, `l3e_unseen_days.png` | L3e | Fits three ways on 10 days, checks on 4 unseen days |
| `twinlab/observer.py` | L4 | The **Luenberger observer**: predict, compare, correct by a fixed gain L |
| `tests/test_observer.py` | L4 | 5 checks: L = 0 is open loop, L = 1 copies the sensor, one step by hand, missing reading, bad gain |
| `run_l4.py`, `l4_observer.png` | L4 | Residual for different gains on 14 days, and how long a lasting sensor fault stays visible |
| `requirements.txt`, `pytest.ini`, `.gitignore` | L1–L3d | Libraries needed, test settings, files git ignores (`data/`, caches) |

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

---

## L3 · The twin loop, in small steps (started 3 Nov 2026)

L3 is split so each piece can be understood and run before the next:

| Step | What | Status |
|---|---|---|
| **L3a** | Load the recording into one dict per moment | ✔ |
| **L3b** | The loop: at each moment, step the 1R1C model with the measured outside temperature and heat, and save its prediction | ✔ |
| **L3c** | Give the model the missing heat sources (lights, plugs, sun), then draw measured vs predicted and the residual | ✔ |
| **L3d** | Fit R, C and sun area from the data instead of guessing them; check on a day the fit never saw | ✔ |

### L3a · Loading the recording

**The problem.** The CSV is "long": one row per reading, so a single moment is spread over 8 rows (zone temp, outside temp, heating and so on). The twin works one moment at a time, so it needs everything taken at that moment together.

**What `load_timesteps()` does** (`twinlab/data.py`, 10 lines):
1. Reads the CSV row by row.
2. Turns `sensor_time` text into a Python datetime.
3. Puts each reading into the dict for its time, creating that dict the first time a time is seen.
4. Returns the dicts sorted oldest first. So even a shuffled file comes out in order.

Result: 2,304 rows become **288 moments**, each like
`{"time": 15 Jan 00:15, "unit1.zone_air_temp": 14.98, "weather1.outside_air_temp": -6.10, "unit1.heat_output": 0.024, ...}`.

**What the first rows show** (`python look_l3a.py`):
- **Zone held at 15 °C overnight** by the thermostat.
- **Outside stays at −6.1 °C for over an hour.** The weather file has hourly values.
- **Heating creeps up** (0.02 → 0.38 kW) even though both temperatures are steady. Two likely reasons: the thermostat's controller slowly winds up, and the concrete walls are still giving off heat they stored during the day, then run out. A 1R1C model has only one heat store, so it can't show that second effect. It's a first, small example of the mismatch the residual will reveal.

**Limitation:** every value is read as a number. That's fine for BOPTEST; text points such as modes would need handling later.

### L3b · The loop (open loop)

**What `run_open_loop()` does** (`twinlab/loop.py`):
1. Starts the model from the **first measured** zone temperature.
2. Walks through the recording in pairs (previous moment, this moment).
3. For each pair, works out the **real time gap** (`dt`, 900 s here), takes the inputs from the *previous* moment, and calls `model.step()`. Using the previous moment's inputs means "assume they stayed the same across the gap", which is the assumption the 1R1C's exact step makes.
4. Saves the prediction. Returns one prediction per moment.

**Two small helpers:**
- `unit_heat_W()`: net heat from the unit = heating − 3.0 × cooling electricity (COP from the test case docs).
- `model_inputs()`: translates plant point IDs (`weather1.outside_air_temp`) into the model's input names (`outside_temp_C`). Neither side needs to know the other's names; when Joe's model arrives, only this translation changes.

**"Open loop"** means the twin never looks at the measured temperature after the start. That tests the model on its own. Pulling it back towards each measurement is the observer's job (L4).

**Guessed R and C** (read off the chart; L3d fits them properly):
- **R ≈ 0.02 K/W.** Just before 08:00 the heating holds about 1.2 kW with about 26 °C between inside (15) and outside (about −11), so roughly 1200 / 26 ≈ 46 W per °C, i.e. R ≈ 0.02.
- **C ≈ 3 MJ/K.** The evening drift closes about 30% of the inside–outside gap in about 7 h, so a time constant of about 17–19 h, and C = time constant / R ≈ 3 × 10⁶. That's heavy, because the concrete stores heat; the air alone would be about 0.16 MJ/K.

### Result: the twin drifts far too cold

`python run_l3b.py`: the measured room stays at 15–24 °C, but the twin falls to around 0 °C and below. Average error about **17 °C**.

**Why** (`python explore_l3b_gains.py`, an energy balance):
- On average the room is 23 °C warmer than outside, so with R = 0.02 it loses about **1,170 W**.
- The unit only gives about **73 W net** on average (heating minus cooling).
- The rest comes from heat sources the twin wasn't told about: lights (about 270 W), plugs (about 120 W), people, and above all **the sun** through 12 m² of south windows.

So the model is starved of heat and slides towards the outside temperature. Adding the missing sources one at a time:

| Heat given to the twin | Average error |
|---|---|
| Unit only | 17.4 °C |
| + lights and plugs | 11.4 °C |
| + lights, plugs, sun × 2 m² | 7.5 °C |
| + lights, plugs, sun × 4 m² | 3.6 °C |
| + lights, plugs, sun × 6 m² | 2.7 °C |

"Sun × area" means sunshine (W/m²) × an *effective* window area (made-up values here; L3d fits it). It isn't the real 12 m², because the sunshine is measured on a flat surface, not the south wall, and glass lets only part of it through.

### What this teaches (worth keeping for the feasibility report)

1. **For this room the unit isn't the main heat source;** the sun and internal gains are. A twin that only knows the unit's heat can't work.
2. **That's likely true of SME sites too:** machines, ovens, people and sun all add heat. So **what the twin is told about other heat sources matters as much as the model itself.** This feeds straight into the "minimum viable sensor set" question (WP4): e.g. is a cheap sunshine sensor, or a power meter on the big machines, worth more than another temperature probe?
3. **Open loop errors pile up.** Each step starts from the last wrong prediction, so mistakes accumulate. The observer (L4) is what stops that in a live twin.

**Next (L3c):** give the 1R1C model the missing heat sources as proper inputs (internal gains, plus sunshine × an area value), then draw measured vs predicted and the residual.

### L3c · All heat sources, and the first residual chart

**Model change (`twinlab/rc1.py`).** The heat `Q` in `C · dT/dt = (T_out − T)/R + Q` is now the sum of:
- the unit's net heat (as before);
- **internal gains**, `internal_gain_W`: lights + plugs, measured;
- **sunshine × effective area**, `solar_W_m2 × solar_area_m2`. The area is a new model value, like R and C, to be fitted in L3d.

Both new inputs are optional (0 if missing), so the model still works where only the unit's heat is known. A new test checks that 1 kW from gains settles the room exactly like 1 kW from the unit. `loop.py`'s `model_inputs()` now passes the two new inputs.

**New `twinlab/metrics.py`:** residual = measured − predicted; MAE (average size of the miss); RMSE (like MAE, but big misses count extra).

**Result** (`python run_l3c.py`; R = 0.02, C = 3 MJ/K, sun area = 5 m², all still guesses):

| | Open loop, unit only (L3b) | Open loop, all heat sources (L3c) |
|---|---|---|
| MAE | 17.4 °C | **2.4 °C** |
| RMSE | not computed | 3.1 °C |

The twin now follows the shape of each day. Chart: `l3c_twin_vs_plant.png`.

**Reading the residual chart.** The same pattern repeats every day, so it's the model's shape, not a fault:
1. **Overnight the twin sinks below 15 °C while the real room holds at 15.** The twin thinks the heating isn't enough. Either R is too small (it loses heat too fast), or the real room is also getting heat back from its concrete walls, a second heat store the 1R1C doesn't have.
2. **At 08:00 the real room jumps 15 → 21 °C in 15 minutes; the twin can't.** Only the *air* heats that fast, and the air stores very little heat. The twin's single C (3 MJ/K) is mostly concrete, so it can only move slowly. **One C can't be both fast (air) and slow (concrete).** This is the classic reason for a 2R2C model (air + fabric), the "TiTe" model of Bacher & Madsen (2011).
3. **Midday the twin overshoots to about 27 °C;** the real room is capped at 24 by cooling. Probably too much sun (area guess too big), or cooling's heat removal underestimated.

**Why it matters:** a fault detector watching this residual would raise a false alarm every morning. Before detection is worth trying, the residual on healthy data needs to be small and patternless. The ways to get there, in order:
- **L3d:** fit R, C and the sun area to the data instead of guessing.
- **L4:** an observer, so errors can't pile up.
- **Possibly a 2R2C model** for the morning jump. Joe's reduced-order model may already be this, so it would plug in here.

**Next (L3d):** fit R, C and the sun area automatically (least squares with SciPy) and see how much of the pattern is left.

### L3d · Fitting R, C and sun area, then checking on an unseen day

**How fitting works (`twinlab/fit.py`, "least squares"):** pick values for R, C and sun area; run the twin; square every residual and add them up. That one number is small when the twin follows the room. SciPy's `least_squares` keeps adjusting the three values in whichever direction makes that number smaller, until it can't improve. Two details:
- R (about 0.02) and C (about 3,000,000) are wildly different sizes, so SciPy works on log(R) and log(C). That puts them on a similar scale and means they can never go negative.
- The sun area can't go below 0.

**Is the fitting code right?** `tests/test_fit.py` makes a fake recording from a 1R1C with values we chose (R = 0.015, C = 4 MJ/K, area = 3 m²). It then asks the fit to find them, starting from wrong guesses. It gets them back within 1%.

**The real test (`python run_l3d.py`):** fit on days 1–2 only, then run on day 3, which the fit never saw (RR 1 §7: "fit on one period, evaluate on a held-out period").

| | R (K/W) | C (MJ/K) | Sun area (m²) | Time constant | MAE days 1–2 | **MAE day 3 (unseen)** |
|---|---|---|---|---|---|---|
| Guessed (L3c) | 0.020 | 3.00 | 5.00 | 16.7 h | 2.35 °C | 2.66 °C |
| Fitted on days 1–2 | 0.037 | 2.71 | 0.88 | 28.0 h | **0.78 °C** | **4.63 °C** |

Chart: `l3d_fitted.png` (day 3 shaded).

### What happened: great on the days it learned from, worse on the new day

- **On days 1–2 the fit is excellent** (0.78 °C). On those numbers alone it would look solved.
- **On day 3 it's worse than our guess** (4.63 vs 2.66 °C). After 08:00 the twin rises to only about 19 °C and then falls away, while the real room sits at 24.
- **The fitted values aren't physically believable.** A sun area of 0.88 m² for a room with 12 m² of south glass is far too small, and R nearly doubled. The fit has found a combination that *happens* to match days 1–2: "less sun coming in, but heat escaping more slowly" gives similar curves on those days. On day 3, though, the sun was strong and cooling worked hardest (the peak in the L2 chart). With almost no sun in the model, the twin can't explain why the room stayed warm while cooling was taking heat out.

This is called **overfitting with values that trade off against each other** (they aren't "identifiable" from this little data). It's a well-known trap, and it's **exactly why RR 1 asks for checking on a held-out period:** the training score alone would have been misleading.

**Ways to fix it, roughly simplest first:**
1. **More, and more varied, data.** Two days is very little. BOPTEST can record two weeks, or other seasons, in minutes.
2. **Fit in stages, as RR 1 §7 describes.** First fit R and C on **night-time cool-downs only**, when there's no sun, so the sun can't trade off against R. Then fit the sun area on daytime data with R and C fixed.
3. **Keep values physically sensible:** e.g. limit the sun area to a believable range.
4. **A better model shape (2R2C).** The morning jump and the overnight hold showed the 1R1C is too simple. Some of what the fit is "bending" to cover is really a missing second heat store. Joe's model may help here.

**Next:** record a longer stretch (about 14 days) from BOPTEST, then try the staged fit (cool-downs first) and check again on unseen days. If the 1R1C still can't hold up on new days, that's the evidence that a 2R2C is needed.

---

### L3e · More data, and fitting in stages (3 Nov 2026)

**New recording:** 14 days (15–28 Jan), `python run_boptest.py --url http://127.0.0.1:8000 --days 14 --out data/boptest_14days.csv`. Outside ranged from −21 to +18 °C, so far more varied than the first 3 days.

**Split:** days 1–10 for fitting, days 11–14 never seen by any fit. Each day is run on its own: the twin starts from that midnight's measured temperature and runs open loop for 24 h. So one bad day can't spoil the next.

**New helpers:**
- `split_days()`: one segment per day.
- `find_cooldowns()`: stretches of at least 2 h with heating off, cooling off and no sun. There are 9 in the training days; RR 1 §7 calls these "free step-response experiments".
- `fit_rc1()` now takes a list of segments (each restarted from its own measurement), can fit only some values (`fit=("R", "solar_area")`), and can fix R × C (`tau_s=`).

**Something learned on the way.** The plan was "R and C from cool-downs, then sun area". In practice the cool-down fit pushed R towards 0 and C towards infinity. A quick check (fit C for several fixed R values) showed every R gives the same answer for **R × C ≈ 26–28 h**. A cool-down shows how *fast* the room cools, not R and C separately. **RR 1 §7 says exactly this:** the decay "yields the time constant", and a period with known heat input is needed to separate R and C. So the staged method became:
1. **Night cool-downs → time constant** R × C = **26.0 h**.
2. **Whole training days → R and sun area,** with R × C held at 26.0 h (so C = 26.0 h / R).

### Results on the 4 unseen days

| | R (K/W) | C (MJ/K) | Sun area (m²) | Time constant | MAE training days | **MAE unseen days** | MAE unseen nights |
|---|---|---|---|---|---|---|---|
| Guessed (L3c) | 0.0200 | 3.0 | 5.0 | 16.7 h | 3.92 °C | 3.14 °C | 1.51 °C |
| One go (L3d method) | 0.0130 | 17.5 | 15.7 | 63.0 h | 1.78 °C | **1.64 °C** | 2.21 °C |
| **Staged (RR 1 §7)** | 0.0114 | 8.2 | 12.1 | 26.0 h | 2.05 °C | **1.85 °C** | **0.79 °C** |

Chart: `l3e_unseen_days.png`.

**What it shows:**
1. **More data fixed the L3d problem.** Fitted on 10 days, both fits now do *better* on unseen days than the guess (1.6–1.9 vs 3.1 °C). In L3d, fitted on 2 days, the fit did worse.
2. **"One go" has the lowest overall error but the wrong physics.** Its time constant (63 h) contradicts the cool-downs (26 h), so its nights are worse (2.21 °C). It has settled on a compromise that's right on average but wrong in each part of the day.
3. **"Staged" is physically consistent.** Its time constant agrees with the cool-downs, so nights are very good (0.79 °C). Its sun area, 12.1 m², is close to the real 12 m² of glass. That's partly luck, since "effective area" also includes how much the glass lets through and the low winter sun on a south wall, but at least it's believable. Its weak spot is the mornings, where it dips below the real room.
4. **Neither can do the 08:00 jump.** With one heat store, the room can't be fast (air) and slow (concrete) at the same time. This is now consistent across 14 days: **the evidence points to a 2R2C model** (separate air and fabric temperatures, Bacher & Madsen's "TiTe").

**Small caveat:** step 1 held R at 0.02 while fitting C. The time constant varies slightly with R (26–28 h across the R values tried), so a second pass at the fitted R would refine it a little. It doesn't change the conclusions.

**How good is "good enough"?** RR 1 §7 doesn't ask for a fixed number: the model must be accurate enough that a realistic fault stands out from normal error. About 1.6–1.9 °C average error, concentrated in a daily pattern, is the baseline that L5 and L6 (fault detection) will be measured against.

**Possible next steps:** (a) a 2R2C model, which the evidence now points to, and which would also show how a second model plugs in (the same path Joe's model will take); (b) L4, the observer, which keeps the twin in step with measurements.

---

## L4 · A Luenberger observer (4 Nov 2026)

**Decision (Loch, 4 Nov):** no 2R2C for now. The 1R1C is good enough to carry on building the pipeline, which is the purpose of this work. Model accuracy (2R2C, ML, more data) is a later, separate piece of work.

**The problem:** open loop, every small model error carries into the next step, so the twin drifts away from the real room over days.

**What the observer does (`twinlab/observer.py`):** at every new reading:
1. **predict:** step the model on from its last state;
2. **compare:** residual = measured − predicted;
3. **correct:** new state = predicted + **L** × residual.

**L, the gain,** is between 0 and 1. L = 0 never corrects (open loop). L = 1 jumps to each reading (the twin just copies the sensor). L = 0.2 moves 20% of the way each step. A fixed L is a **Luenberger observer**; a Kalman filter has the same shape but works L out from how noisy the sensor and model are. The residual is now a **one-step-ahead** error: it's measured against a prediction made 15 minutes after the last correction.

**Missing reading:** no correction that step. The twin carries on from its prediction ("coasts"), and the residual is `None`.

### Results (`python run_l4.py`, fitted values from L3e: R 0.0114, C 8.23 MJ/K, sun 12.12 m²)

**Part 1, healthy data, 14 days:**

| Gain L | Residual MAE | Moments with residual over 1 °C |
|---|---|---|
| 0 (open loop) | 2.33 °C | 975 of 1,343 |
| 0.05 | 1.47 °C | 690 |
| 0.1 | 1.12 °C | 543 |
| **0.2** | **0.74 °C** | 307 |
| 0.3 | 0.55 °C | 214 |
| 0.5 | 0.36 °C | 75 |
| 1.0 | 0.21 °C | 24 |

**Part 2, the catch.** The sensor suddenly reads 2 °C too high from 02:00 on 26 Jan and stays wrong (a lasting fault):

| Gain L | Residual straight after | Time until the residual is back under 1 °C |
|---|---|---|
| 0.05 | 2.8 °C | 11.25 h |
| 0.1 | 2.3 °C | 3.25 h |
| 0.3 | 2.1 °C | 0.75 h |
| 0.5 | 2.0 °C | 0.5 h |

Chart: `l4_observer.png`. Top: healthy residual, open loop vs L = 0.2. Bottom: the fault, L = 0.05 vs 0.5.

### What it shows

1. **The observer works:** with L = 0.2 the healthy residual falls from 2.3 to 0.7 °C, and the slow drifts disappear.
2. **The 08:00 spikes remain** (about 6 °C) at every gain. A jump of 6 °C in 15 minutes can't be predicted one step ahead by this model. It happens every working day, so the detector (L5) must not treat it as a fault: e.g. ignore residuals right after a known setpoint change, or accept it until a better model comes.
3. **The observer can't tell a model error from a fault.** A big gain pulls the twin onto a faulty sensor within 30 minutes, so a lasting fault shows up only as a short spike. A small gain keeps the fault visible for hours, but carries a bigger everyday error (L = 0.05 sat about 1 °C off even before the fault).
4. **So L has to be chosen together with the detector,** in L5. L = 0.2 is a placeholder until then. Detectors that add up the residual over time (CUSUM) can still catch a fault that a big gain has absorbed. Another common approach is to run an open-loop copy of the twin alongside the observer, just for slow faults. Both are options for L5.

**Not done yet (possible small L4b):** the LIVE / COASTING / STALE data state from the project's design. The observer already coasts through a missing reading; the state machine would label how long it has been coasting, so detection can be switched off when data goes stale.
