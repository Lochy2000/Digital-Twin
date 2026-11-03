"""1R1C model: one zone, one heat store, one path for heat to escape.

The physics (heat balance on the zone):

    C * dT/dt = (T_out - T) / R + Q

    T      zone temperature (°C)
    T_out  outside temperature (°C)
    Q      all heat put into the zone (W), added up from:
             Q_unit    the heat/cool unit: positive = heating, negative = cooling
             Q_int     internal gains: lights, computers, machines (measured)
             A * S     sunshine: S = sunshine (W/m2), A = effective window area (m2)
    R      thermal resistance (K/W): how hard it is for heat to escape
    C      thermal capacitance (J/K): how much heat the zone stores
    A      effective sun-catching area (m2), a value to be fitted (L3d), like R and C

Internal gains and sunshine are optional inputs (0 if not given), so the model
still works where only the unit's heat is known. Added in L3c, after L3b showed
that leaving them out starves the model of heat.

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
    inputs = ["outside_temp_C", "unit_heat_W", "internal_gain_W", "solar_W_m2"]
    outputs = ["zone_temp_C"]

    def __init__(self, R: float, C: float, solar_area_m2: float = 0.0):
        if R <= 0 or C <= 0:
            raise ValueError("R and C must be positive")
        if solar_area_m2 < 0:
            raise ValueError("solar area can't be negative")
        self.R = R                          # K/W
        self.C = C                          # J/K
        self.solar_area_m2 = solar_area_m2  # m2

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
        Q = (inputs["unit_heat_W"]
             + inputs.get("internal_gain_W", 0.0)
             + self.solar_area_m2 * inputs.get("solar_W_m2", 0.0))
        T_balance = inputs["outside_temp_C"] + self.R * Q
        T_new = T_balance + (T - T_balance) * math.exp(-dt / self.time_constant_s)
        return {"zone_temp_C": T_new}

    def predict(self, state: Values) -> Values:
        return {"zone_temp_C": state["zone_temp_C"]}
