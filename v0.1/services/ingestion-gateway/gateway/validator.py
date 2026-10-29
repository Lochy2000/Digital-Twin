"""
Validator: "is this reading believable?"

Takes a normalised reading (from the normaliser) plus its PointMapping and decides its
`quality`: GOOD, SUSPECT or BAD. It never changes or drops the reading: a BAD reading is
still stored, with its flag, so nothing is lost and the flag can be revisited. (Readings
the gateway can't understand at all go to quarantine earlier; that's a different thing.)

The checks are the stateless ones from QARTOD, the US IOOS quality-control standard for
real-time sensor data, as implemented in the ioos_qc library:

    qc test name     QARTOD test            result if it fails
    ---------------  ---------------------  ------------------------------------------
    sensor_range     gross range, fail      BAD      the sensor can't measure this
    expected_range   gross range, suspect   SUSPECT  possible, but not what we expect here
    future_time      impossible date        BAD      a reading from the future
    late_arrival     data reception         SUSPECT  older than max_age when it arrived

late_arrival is SUSPECT, not FAIL as in ioos_qc's data_reception_test (step 2j). That test
asks "is this stream current?", which ioos_qc says is "intended for data centers or streams".
Here, a late reading is usually our own delay (e.g. the broker replaying messages queued while
the gateway was down): the value is still a real measurement, so it is kept usable for history
and flagged. Whether it is too old to drive the LIVE twin is the twin's call (its
LIVE / COASTING / STALE state), not the gateway's ("translate and check, never interpret").

Each check gives a QARTOD flag; every flag is reported in the message's `qc` list (message v2,
step 2i), and the worst one wins (FAIL > SUSPECT > GOOD, the same
order as ioos_qc's qartod_compare). Ranges come from the mapper (sensor range from the
device type, expected range from the asset model), already in the point's unit.

Our three words are QARTOD's flags 1 / 3 / 4, and match OPC UA's Good / Uncertain / Bad:

    GOOD = QARTOD 1 "pass"      SUSPECT = QARTOD 3 "suspect"      BAD = QARTOD 4 "fail"

Not done yet (they need the previous readings of each point, i.e. state):
spike, rate of change, flat line ("stuck sensor"), duplicates. See NOTES.md.

Sources:
  - QARTOD tests and flag values, ioos_qc 3.0.0 (qartod.py: gross_range_test,
    impossible_date_test, data_reception_test, qartod_compare, QartodFlags):
      https://github.com/ioos/ioos_qc      https://pypi.org/p/ioos-qc
  - OPC UA quality: Good / Uncertain / Bad (OPC 10000-8, Annex A):
      https://reference.opcfoundation.org/specs/OPC-10000-8/a-4-3-3
  - Where the ranges come from: mappings/dtteo_onboarding.ttl (W3C SSN MeasurementRange)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .mapper import PointMapping

# QARTOD primary flags (ioos_qc QartodFlags) and our words for them.
PASS, SUSPECT_FLAG, FAIL = 1, 3, 4
QUALITY = {PASS: "GOOD", SUSPECT_FLAG: "SUSPECT", FAIL: "BAD"}

# Defaults. Both are our choices, stated so they can be changed:
FUTURE_TOLERANCE = timedelta(seconds=60)   # device clocks drift; QARTOD flags ANY future time,
                                           # we allow a minute of clock difference first
MAX_AGE = timedelta(hours=6)               # ioos_qc data_reception_test default (fail_span=6 hours).
                                           # A CSV back-fill turns it off (max_age=None).


@dataclass(frozen=True)
class Check:
    test: str                   # qc test name, e.g. "expected_range"
    flag: int                   # QARTOD flag: SUSPECT_FLAG or FAIL
    reason: str                 # plain English, e.g. "40.0 is outside the expected range 5.0..35.0"

    def as_qc(self) -> dict:
        """The shape used in the canonical message's `qc` list."""
        return {"test": self.test, "flag": QUALITY[self.flag], "reason": self.reason}


@dataclass(frozen=True)
class Verdict:
    quality: str                # "GOOD" / "SUSPECT" / "BAD"
    checks: tuple[Check, ...]   # every check that flagged the reading (empty if GOOD)

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(c.reason for c in self.checks)


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(reading: dict, mapping: PointMapping,
             future_tolerance: timedelta = FUTURE_TOLERANCE,
             max_age: timedelta | None = MAX_AGE) -> Verdict:
    flags: list[Check] = []
    value = reading["value"]

    # Gross range test. Only for numbers: words like "cool" were already checked by the value map.
    if _is_number(value):
        if mapping.fail_span:
            lo, hi = mapping.fail_span
            if not lo <= value <= hi:
                flags.append(Check("sensor_range", FAIL, f"{value} is outside the sensor's range {lo}..{hi}"))
        if mapping.suspect_span:
            lo, hi = mapping.suspect_span
            if not lo <= value <= hi:
                flags.append(Check("expected_range", SUSPECT_FLAG, f"{value} is outside the expected range {lo}..{hi}"))

    # Time tests: compare the device's time with when we received it.
    sensor, ingest = _time(reading["sensor_time"]), _time(reading["ingest_time"])
    if sensor > ingest + future_tolerance:
        flags.append(Check("future_time", FAIL, f"sensor_time is {sensor - ingest} in the future"))
    if max_age is not None and ingest - sensor > max_age:
        flags.append(Check("late_arrival", SUSPECT_FLAG,
                           f"reading was {ingest - sensor} old when it arrived (limit {max_age})"))

    worst = max((c.flag for c in flags), default=PASS)
    return Verdict(QUALITY[worst], tuple(flags))


def with_quality(reading: dict, mapping: PointMapping, **kwargs) -> tuple[dict, Verdict]:
    """The reading plus its quality (and qc list if not GOOD): a complete canonical message
    (contracts/canonical_message.schema.json)."""
    verdict = validate(reading, mapping, **kwargs)
    message = {**reading, "quality": verdict.quality}
    if verdict.checks:
        message["qc"] = [c.as_qc() for c in verdict.checks]
    return message, verdict
