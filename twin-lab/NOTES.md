# Twin lab: build notes

One entry per step, newest at the bottom. Each says what was done, why, and what to check.

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
