"""Validate the whole dataset: the products, the card spine, sets/, the mappings and the UUID registry. Exit 1 on any
problem.

    python tools/validate.py              # schemas, ids, layout, nested products, links to the spine, UUIDs
    python tools/validate.py --since REF  # also: no UUID data/uuids/ gave at git ref REF was dropped or changed
    python tools/validate.py --online     # also check every product's cards against the TCGdex API
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import spine
import uuids
from pkmjson import CARDS, SEALED, SERIES, SETS, UUIDS, file_errors, validate, validate_cards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=SEALED, type=Path)
    parser.add_argument("--cards", default=CARDS, type=Path)
    parser.add_argument("--sets", default=SETS, type=Path)
    parser.add_argument("--series", default=SERIES, type=Path)
    parser.add_argument("--registry", default=UUIDS, type=Path)
    parser.add_argument("--since", metavar="REF", help="git ref whose data/uuids/ the current one must extend")
    parser.add_argument("--online", action="store_true", help="check cards against the TCGdex API")
    args = parser.parse_args(argv)
    whole = uuids.Spine.load(args.data, args.series, args.sets, args.cards, args.registry)
    errors = file_errors(args.sets, registry=args.registry, series_path=args.series)
    errors += validate(whole.families, args.data, sets=whole.sets)
    if not errors:
        errors += spine.errors(whole, uuids.load_registry(args.registry))
    if args.since:
        errors += uuids.history_errors(uuids.registry_at(args.since), uuids.load_registry(args.registry))
    if not errors and args.online:
        errors = validate_cards(whole.families, args.data)
    for error in errors:
        print(error, file=sys.stderr)
    cards = sum(len(b["cards"]) for b in whole.cards.values())
    print(f"{len(whole.sets)} sets, {cards} cards, {len(whole.families)} products, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
