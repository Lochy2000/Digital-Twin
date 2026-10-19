"""
Checks every example message against the canonical message schema.

  examples/valid/*.json    must PASS
  examples/invalid/*.json  must FAIL

Run:  python check_examples.py
This is the first "contract test". Later, each adapter's output will be
checked the same way.

Sources:
  - JSON Schema 2020-12 (the schema's "$schema"):  https://json-schema.org/draft/2020-12/schema
  - Message shape modelled on SenML (RFC 8428):    https://datatracker.ietf.org/doc/rfc8428/
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

HERE = Path(__file__).parent
schema = json.loads((HERE / "canonical_message.schema.json").read_text())
validator = Draft202012Validator(schema, format_checker=FormatChecker())

failures = 0
for expected, folder in (("pass", "valid"), ("fail", "invalid")):
    for path in sorted((HERE / "examples" / folder).glob("*.json")):
        errors = list(validator.iter_errors(json.loads(path.read_text())))
        ok = (not errors) if expected == "pass" else bool(errors)
        status = "OK  " if ok else "FAIL"
        print(f"{status} {folder}/{path.name}")
        for e in errors:
            where = "/".join(map(str, e.path)) or "(message)"
            print(f"       -> {where}: {e.message}")
        failures += not ok

print("\nall examples behave as expected" if not failures else f"\n{failures} example(s) did not behave as expected")
sys.exit(1 if failures else 0)
