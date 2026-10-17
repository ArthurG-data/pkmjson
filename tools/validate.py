"""Validate every product file. Exit 1 on any problem.

    python tools/validate.py            # schema, ids, layout, nested products, languages
    python tools/validate.py --online   # also check every card against the TCGdex API
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pkmjson import ROOT, load, validate, validate_cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--online", action="store_true", help="check cards against the TCGdex API")
    args = parser.parse_args(argv)
    families = load(args.data)
    errors = validate(families, args.data)
    if not errors and args.online:
        errors = validate_cards(families, args.data)
    for error in errors:
        print(error, file=sys.stderr)
    print(f"{len(families)} products, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
