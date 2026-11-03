"""The twin loop, simplest version: step a model through a recording.

"Open loop" means the model is started from the first measured temperature
and then runs on its inputs alone; it never looks at the measured temperature
again. That tests the model on its own. Pulling it back towards each new
measurement (an "observer") comes later, in L4.
"""

# bestest_air measures cooling as electricity used. Its documentation says the
# chiller's COP is fixed at 3.0, so heat removed = 3.0 x cooling electricity.
COP_COOLING = 3.0


def unit_heat_W(moment: dict) -> float:
    """Net heat the unit puts into the room, in watts: heating minus cooling."""
    heating_kW = moment["unit1.heat_output"]
    cooling_kW = COP_COOLING * moment["unit1.cool_power"]
    return 1000 * (heating_kW - cooling_kW)


def model_inputs(moment: dict) -> dict:
    """Translate one moment of plant readings into the model's input names.

    The plant uses point IDs (e.g. "weather1.outside_air_temp"); the model uses
    its own input names (e.g. "outside_temp_C"). Keeping the translation here
    means neither side needs to know the other's names.
    """
    return {
        "outside_temp_C": moment["weather1.outside_air_temp"],
        "unit_heat_W": unit_heat_W(moment),
        # L3c: the heat sources L3b showed the model was missing
        "internal_gain_W": 1000 * (moment["zone1.lighting_power"] + moment["zone1.plug_power"]),
        "solar_W_m2": moment["weather1.solar_global"],
    }


def run_open_loop(model, moments: list[dict]) -> list[float]:
    """Return the model's predicted zone temperature for every moment."""
    first = moments[0]
    state = model.initial_state({"zone_temp_C": first["unit1.zone_air_temp"]})
    predictions = [model.predict(state)["zone_temp_C"]]

    # Walk through the recording in pairs: (previous moment, this moment).
    for prev, now in zip(moments, moments[1:]):
        dt = (now["time"] - prev["time"]).total_seconds()  # real gap, not assumed
        # Inputs from the START of the gap, assumed to stay the same across it.
        # That's the assumption the 1R1C's exact step makes ("zero-order hold").
        state = model.step(state, model_inputs(prev), dt)
        predictions.append(model.predict(state)["zone_temp_C"])

    return predictions
