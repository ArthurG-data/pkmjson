"""Write dist/AllProducts.json (one entry per product and language) and dist/AllSets.json (each set's printed name
and logo per language), each with its schema beside it (dist/AllProducts.schema.json, ...).

    uv run python tools/build.py --version 0.2.0 [--date 2026-11-27]

It refuses to build invalid data, or a file its schema does not describe, and then writes nothing: dist/ holds
the files of one build or of none. meta.date is the date of the data, not of the build: by default the day of the
last commit that changed sets/ or data/, so building one commit twice writes the same files.
"""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

import release_schema
from pkmjson import ROOT, SETS, file_errors, flatten, load, read_json, validate, write_json

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


def outputs(data: Path, sets_path: Path, meta: dict) -> dict[str, dict]:
    """{file name: document} for every release file and schema, or Invalid."""
    families = load(data)
    sets = read_json(sets_path) if sets_path.exists() else {}
    registry = data / "uuids.json"
    errors = validate(families, data, sets=sets) + file_errors(sets_path, registry=registry)
    if errors:
        raise Invalid("refusing to build:\n" + "\n".join(errors[:50]))
    documents = {"AllProducts": {"meta": meta, "data": flatten(families)}, "AllSets": {"meta": meta, "data": sets}}
    schemas = release_schema.schemas()
    errors = [f"{name}.json: {e.json_path}: {e.message}" for name, doc in documents.items()
              for e in Draft202012Validator(schemas[name], format_checker=FormatChecker()).iter_errors(doc)]
    if errors:
        raise Invalid("refusing to build: the release files do not match their schemas:\n" + "\n".join(errors[:50]))
    return {**{f"{n}.json": d for n, d in documents.items()}, **{f"{n}.schema.json": s for n, s in schemas.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--sets", default=SETS, type=Path)
    parser.add_argument("--out", default=DIST, type=Path)
    parser.add_argument("--version", default="0.0.0-dev")
    parser.add_argument("--date", type=dt.date.fromisoformat, help="meta.date; default: the day sets/ or data/ last changed")
    args = parser.parse_args(argv)
    meta = {"version": args.version, "date": args.date.isoformat() if args.date else data_date()}
    try:
        files = outputs(args.data, args.sets, meta)
    except Invalid as error:
        print(error, file=sys.stderr)
        return 1
    for name, doc in files.items():
        write_json(args.out / name, doc, indent=1)
    products, sets = files["AllProducts.json"]["data"], files["AllSets.json"]["data"]
    print(f"{len(products)} product releases, {len(sets)} sets -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
