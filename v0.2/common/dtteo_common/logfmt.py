"""
One log line per event, key=value ("logfmt"), shared by every DT-TEO service.

    kv("quarantine", stage="map", field="rh")   ->   'quarantine stage=map field=rh'

Moved here from the v0.1 gateway (pipeline.py) so the historian can use it without
importing gateway code.

Source: logfmt  https://brandur.org/logfmt
"""
from __future__ import annotations

import json
import re
from typing import Any


def kv(event: str, **fields: Any) -> str:
    """logfmt line: kv("quarantine", stage="map", field="rh") -> 'quarantine stage=map field=rh'"""
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        if text == "" or re.search(r'[\s="]', text):
            text = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
        parts.append(f"{key}={text}")
    return " ".join(parts)
