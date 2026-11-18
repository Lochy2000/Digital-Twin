"""The message contracts (JSON Schemas), installed as dtteo_common.contracts.

    from dtteo_common.contracts import schema_path
    schema_path("canonical")   -> .../canonical_message.schema.json
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def schema_path(kind: str) -> Path:
    """kind: "canonical" or "quarantine"."""
    return HERE / f"{kind}_message.schema.json"
