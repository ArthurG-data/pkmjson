"""Write dist/AllProducts.json: one entry per product and language. Refuses to build invalid data."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from pkmjson import ROOT, flatten, load, validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--out", default=ROOT / "dist", type=Path)
    parser.add_argument("--version", default="0.0.0-dev")
    args = parser.parse_args(argv)
    families = load(args.data)
    errors = validate(families, args.data)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    products = flatten(families)
    args.out.mkdir(parents=True, exist_ok=True)
    payload = {"meta": {"version": args.version, "date": dt.date.today().isoformat()}, "data": products}
    (args.out / "AllProducts.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                                               encoding="utf-8")
    print(f"{len(families)} products, {len(products)} language releases -> {args.out / 'AllProducts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
