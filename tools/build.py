"""Write dist/AllProducts.json (one entry per product and language) and dist/AllSets.json (each set's printed name
and logo per language), each with its schema beside it (dist/AllProducts.schema.json, ...).

    uv run python tools/build.py --version 0.2.0 [--date 2026-11-27]

It refuses to build invalid data, or a file its schema does not describe, and then writes nothing: dist/ holds
the files of one build or of none.

The release files are AllSets, AllCards, AllPrintings, AllProducts and AllUuids. meta.sources names the TCGdex commit the
cards come from.

meta.date is the date of the data, not of the build: by default the day of the
last commit that changed sets/ or data/, so building one commit twice writes the same files.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

import net
import release_schema
import spine
import uuids
from pkmjson import CARDS, MAPPINGS, ROOT, SEALED, SERIES, SETS, UUIDS, file_errors, read_json, validate, write_json

DIST = ROOT / "dist"


class Invalid(Exception):
    """The data or the files built from it are not valid: nothing is written."""


def data_date(root: Path = ROOT) -> str:
    """The day of the last commit that changed sets/ or data/; today when git cannot say."""
    try:
        shown = subprocess.run(["git", "log", "-1", "--format=%cs", "--", "sets", "data"], cwd=root,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        shown = ""
    return shown or dt.date.today().isoformat()


def outputs(whole: uuids.Spine, meta: dict, sets_path: Path = SETS, series_path: Path = SERIES) -> dict[str, dict]:
    """{file name: document} for every release file and schema, or Invalid."""
    errors = file_errors(sets_path, registry=whole.registry_path, series_path=series_path)
    errors += validate(whole.families, whole.sealed_path, sets=whole.sets)
    if not errors:
        errors = spine.errors(whole, uuids.load_registry(whole.registry_path))
    if errors:
        raise Invalid("refusing to build:\n" + "\n".join(errors[:50]))
    cards, prints = spine.all_cards_and_printings(whole)
    data = {"AllSets": spine.all_sets(whole), "AllCards": cards, "AllPrintings": prints,
            "AllProducts": spine.all_products(whole)}
    data["AllUuids"] = spine.all_uuids(whole.sets, cards, prints, data["AllProducts"], whole.series)
    documents = {name: {"meta": meta, "data": records} for name, records in data.items()}
    schemas = release_schema.schemas()
    errors = [f"{name}.json: {e.json_path}: {e.message}" for name, doc in documents.items()
              for e in Draft202012Validator(schemas[name], format_checker=FormatChecker()).iter_errors(doc)]
    if errors:
        raise Invalid("refusing to build: the release files do not match their schemas:\n" + "\n".join(errors[:50]))
    return {**{f"{n}.json": d for n, d in documents.items()}, **{f"{n}.schema.json": s for n, s in schemas.items()}}


def sources() -> dict[str, str]:
    """The snapshot each source was read at, as mappings/sources.json pins it."""
    pinned = read_json(MAPPINGS / "sources.json")
    return {"tcgdex": pinned["tcgdex"]["commit"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=SEALED, type=Path)
    parser.add_argument("--sets", default=SETS, type=Path)
    parser.add_argument("--series", default=SERIES, type=Path)
    parser.add_argument("--cards", default=CARDS, type=Path)
    parser.add_argument("--registry", default=UUIDS, type=Path)
    parser.add_argument("--out", default=DIST, type=Path)
    parser.add_argument("--version", default="0.0.0-dev")
    parser.add_argument("--date", type=dt.date.fromisoformat, help="meta.date; default: the day sets/ or data/ last changed")
    args = parser.parse_args(argv)
    meta = {"version": args.version, "date": args.date.isoformat() if args.date else data_date(),
            "sources": sources()}
    try:
        files = outputs(uuids.Spine.load(args.data, args.series, args.sets, args.cards, args.registry), meta,
                        args.sets, args.series)
    except Invalid as error:
        print(error, file=sys.stderr)
        return 1
    for name, doc in files.items():
        if name.endswith(".schema.json"):
            write_json(args.out / name, doc)
        else:   # compact: AllPrintings alone is over 100 MB indented
            net.write_atomic(args.out / name, json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")
    counts = {name: len(files[f"{name}.json"]["data"]) for name in ("AllSets", "AllCards", "AllPrintings", "AllProducts")}
    print(", ".join(f"{n} {name}" for name, n in counts.items()) + f" -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
