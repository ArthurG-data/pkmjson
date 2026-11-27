"""Helpers the tests share."""
import json

import uuids
from pkmjson import load


def write_families(tmp_path, *families):
    """Write each family where validate expects it, with the UUIDs tools/uuids.py would give it, and load them
    back. The registry is not written, so validate skips its UUID checks."""
    uuids.assign(families, uuids.empty())
    for f in families:
        path = tmp_path / f["region"] / f["set"] / f"{f['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(f), encoding="utf-8")
    return load(tmp_path)
