"""1R1C model: one zone, one heat store, one path for heat to escape.

The physics (heat balance on the zone):

    C * dT/dt = (T_out - T) / R + Q

    T      zone temperature (°C)
    T_out  outside temperature (°C)
    Q      heat the unit puts in (W): positive = heating, negative = cooling
    R      thermal resistance (K/W): how hard it is for heat to escape
    C      thermal capacitance (J/K): how much heat the zone stores

How we step it forward
----------------------
If Q and T_out stay the same over the step, the zone heads towards a
"balance" temperature where heat in equals heat out:

    T_balance = T_out + R * Q

and each step it closes the gap to that temperature by the same fraction:

    T_new = T_balance + (T - T_balance) * exp(-dt / (R * C))

`R * C` is the time constant (seconds): after one time constant the zone has
closed about 63% of the gap. This formula is the exact solution of the
equation above, so it stays correct even for long or uneven steps (a simpler
"Euler" step can overshoot when dt is large). Uneven steps matter because the
twin steps by the real time between readings, not a fixed timer.
"""

import math

from twinlab.model import Values


class RC1:
    inputs = ["outside_temp_C", "unit_heat_W"]
    outputs = ["zone_temp_C"]

    def __init__(self, R: float, C: float):
        if R <= 0 or C <= 0:
            raise ValueError("R and C must be positive")
        self.R = R  # K/W
        self.C = C  # J/K

    @property
    def time_constant_s(self) -> float:
        return self.R * self.C

    def initial_state(self, outputs: Values) -> Values:
        # For 1R1C the state IS the zone temperature, so start from the reading.
        return {"zone_temp_C": outputs["zone_temp_C"]}

    def step(self, state: Values, inputs: Values, dt: float) -> Values:
        if dt < 0:
            raise ValueError("dt can't be negative (readings out of order?)")
        T = state["zone_temp_C"]
        T_balance = inputs["outside_temp_C"] + self.R * inputs["unit_heat_W"]
        T_new = T_balance + (T - T_balance) * math.exp(-dt / self.time_constant_s)
        return {"zone_temp_C": T_new}

    def predict(self, state: Values) -> Values:
        return {"zone_temp_C": state["zone_temp_C"]}
