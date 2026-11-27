"""Validate every product file, sets/sets.json, the mappings and the UUID registry. Exit 1 on any problem.

    python tools/validate.py              # schemas, ids, layout, nested products, languages, owners, UUIDs
    python tools/validate.py --since REF  # also: no UUID data/uuids.json gave at git ref REF was dropped or changed
    python tools/validate.py --online     # also check every card against the TCGdex API
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uuids
from pkmjson import ROOT, SETS, file_errors, load, read_json, validate, validate_cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--sets", default=SETS, type=Path)
    parser.add_argument("--since", metavar="REF", help="git ref whose data/uuids.json the current one must extend")
    parser.add_argument("--online", action="store_true", help="check cards against the TCGdex API")
    args = parser.parse_args(argv)
    families = load(args.data)
    registry = args.data / "uuids.json"
    errors = file_errors(args.sets, registry=registry)
    errors += validate(families, args.data, sets=read_json(args.sets) if args.sets.exists() else None)
    if args.since:
        errors += uuids.history_errors(uuids.registry_at(args.since, registry), uuids.load_registry(registry))
    if not errors and args.online:
        errors = validate_cards(families, args.data)
    for error in errors:
        print(error, file=sys.stderr)
    print(f"{len(families)} products, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
