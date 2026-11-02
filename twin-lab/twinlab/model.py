"""The model interface: the one shape every model must have.

The twin loop only ever talks to a model through this interface, so any model
(the 1R1C below, the modeller's Python model, an FMU, an ML model later) can be
swapped in by writing a small wrapper that looks like this.

The idea follows two established sources:
  - RR 1 section 7: a model "receives a current state, a set of inputs covering
    the period being advanced, and a duration, and it returns the state at the
    end of that period".
  - FMI co-simulation (fmi-standard.org): a model lists its inputs and outputs
    with units, and is advanced with a "do step" call. Our `step()` is the same
    idea in plain Python.

Words used here
  state    the numbers the model remembers between steps (e.g. zone temperature)
  inputs   what the outside world gives it this step (e.g. outside temperature)
  outputs  what it predicts that a sensor could check (e.g. zone temperature)
  dt       how many seconds to move forward
"""

from typing import Protocol

# A state, a set of inputs or a set of outputs is just a dict of name -> number,
# e.g. {"zone_temp_C": 21.5}. Plain dicts keep it easy to read and to save.
Values = dict[str, float]


class Model(Protocol):
    """Anything with these attributes and methods counts as a model.

    `Protocol` means a class doesn't have to inherit from this: if it has the
    same attributes and methods, Python's type checker treats it as a Model.
    """

    inputs: list[str]    # names of the inputs it needs, e.g. ["outside_temp_C"]
    outputs: list[str]   # names of the outputs it predicts, e.g. ["zone_temp_C"]

    def initial_state(self, outputs: Values) -> Values:
        """Make a starting state from a first set of measurements."""
        ...

    def step(self, state: Values, inputs: Values, dt: float) -> Values:
        """Move forward `dt` seconds and return the NEW state.

        Must not change `state` in place. Returning a new dict means a what-if
        run can start from a copy of the live state without touching it.
        """
        ...

    def predict(self, state: Values) -> Values:
        """What the sensors should read, given this state."""
        ...
