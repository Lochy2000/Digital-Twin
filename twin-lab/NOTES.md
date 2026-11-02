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
