"""L4: a Luenberger observer, which keeps the twin in step with the measurements.

The problem it solves
---------------------
Open loop (L3), the twin starts from one measurement and then runs on its
inputs alone. Every small model error is carried into the next step, so over
days the twin drifts away from the real room.

What the observer does: predict, compare, correct
-------------------------------------------------
At every new reading:

    1. predict   step the model forward from its last state    -> predicted
    2. compare   residual = measured - predicted
    3. correct   new state = predicted + L x residual

L is the observer GAIN, a number between 0 and 1:
    L = 0     never correct: the same as open loop
    L = 1     jump fully to the measurement: the twin just copies the sensor
    L = 0.3   move 30% of the way towards the measurement each step

This "predict, then nudge towards the measurement by a fixed gain" is the
Luenberger observer (Luenberger, 1964). A Kalman filter has the same shape,
but works L out from how noisy the sensor and the model are.

The residual is now measured against a prediction made only ONE STEP ahead,
from a state that was corrected 15 minutes ago. It stays small and centred on
zero when the room behaves as the model expects, and jumps when it suddenly
doesn't, which is what fault detection (L5) will watch.

The catch with L: the observer can't tell a model error from a fault. A big
L pulls the twin onto a faulty sensor within a few steps, so the residual
from a lasting fault fades away quickly. A small L keeps the residual from a
lasting fault visible for longer, but corrects model error more slowly.
Choosing L is a trade-off; run_l4.py shows it.

Missing measurement: no correction that step. The twin just carries on from
its prediction (it "coasts"), and that moment's residual is None.
"""

from twinlab.loop import model_inputs

# Which plant point is the measurement of which model output.
MEASURED = {"zone_temp_C": "unit1.zone_air_temp"}


class LuenbergerObserver:
    def __init__(self, model, gain: float, output: str = "zone_temp_C"):
        if not 0.0 <= gain <= 1.0:
            raise ValueError("gain must be between 0 and 1")
        self.model = model
        self.gain = gain
        self.output = output

    def run(self, moments: list[dict]) -> list[dict]:
        """Go through a recording; return one record per moment.

        Each record: time, measured, predicted, residual, corrected.
        """
        key = MEASURED[self.output]
        first = moments[0]
        state = self.model.initial_state({self.output: first[key]})
        start = self.model.predict(state)[self.output]
        records = [{"time": first["time"], "measured": first[key], "predicted": start,
                    "residual": 0.0, "corrected": start}]

        for prev, now in zip(moments, moments[1:]):
            dt = (now["time"] - prev["time"]).total_seconds()

            # 1. predict
            state = self.model.step(state, model_inputs(prev), dt)
            predicted = self.model.predict(state)[self.output]

            # 2. compare, and 3. correct (only if there is a measurement)
            measured = now.get(key)
            if measured is None:
                residual = None
            else:
                residual = measured - predicted
                # For the 1R1C the state IS the zone temperature, so the
                # correction is applied to it directly.
                state = {**state, self.output: state[self.output] + self.gain * residual}

            records.append({"time": now["time"], "measured": measured, "predicted": predicted,
                            "residual": residual, "corrected": state[self.output]})
        return records
