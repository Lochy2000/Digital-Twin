"""dtteo_common's own tests: the installed contracts and the log format.
Run from common/:   python -m pytest -q        (after: pip install -e .)"""
import json

from dtteo_common.contracts import HERE, schema_path
from dtteo_common.logfmt import kv


def test_both_schemas_are_installed_and_are_json():
    for kind in ("canonical", "quarantine"):
        assert json.loads(schema_path(kind).read_text())["$schema"].startswith("https://json-schema.org/")


def test_examples_are_installed_with_the_schemas():
    assert sorted(p.name for p in (HERE / "examples" / "valid").glob("*.json"))


def test_kv_quotes_only_when_needed():
    assert kv("quarantine", stage="map", field="rh", skip=None) == "quarantine stage=map field=rh"
    assert kv("x", reason="two words") == 'x reason="two words"'
