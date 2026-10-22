"""Give every booster pack its `contents.pool`: the TCGdex sets whose cards the pack can hold, at random.

A pack holds its own set, when TCGdex lists that set in the family's tree (English for `international`, Japanese
for `asia`). mappings/pack_pools.json adds the subsets TCGdex files as a set of their own (Hidden Fates' Shiny Vault,
Celebrations' Classic Collection) and names the families that are no single set's pack. A pack whose set TCGdex does
not list, or that the mapping excludes, gets no pool, and review/pack-pools.json says why.

The pool is derived from the family's `set`, TCGdex and the mapping, so a re-run gives the same result and
repairs a file another tool rewrote. import_tcgplayer.py also keeps a pool it finds in a file it regenerates.

    uv run python tools/import_pools.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from import_tcgplayer import TCGDEX_API, Fetcher
from pkmjson import PACK_CATEGORIES, ROOT, Family, load, validate

TCGDEX_LANGUAGE = {"international": "en", "asia": "ja"}
OUT_OF_SCOPE = "Which cards a pack can hold is out of scope for this dataset."
POOL_NOTE = "Which sets' cards it can hold is listed in contents.pool."


def pool_for(data: dict, tcgdex: dict[str, set[str]], extra_sets: dict[str, list[str]],
             excluded: dict[str, str]) -> tuple[list[dict] | None, str | None]:
    """(pool, None) for a pack, or (None, why) when it gets no pool. `tcgdex` maps a region to the set ids TCGdex
    lists for it, `extra_sets` maps '<region>/<set>' to the subsets filed as sets of their own."""
    region, set_id = data["region"], data["set"]
    if data["id"] in excluded:
        return None, excluded[data["id"]]
    if set_id not in tcgdex[region]:
        return None, f"{set_id} is not a TCGdex {TCGDEX_LANGUAGE[region]} set"
    return [{"set": s} for s in [set_id, *extra_sets.get(f"{region}/{set_id}", [])]], None


def with_pool(data: dict, pool: list[dict] | None) -> dict:
    """The family with its pool set (or removed, for None) and its note no longer saying pools are out of scope."""
    contents = {k: v for k, v in data["contents"].items() if k != "pool"}
    if pool:
        contents["pool"] = pool
    out = {**data, "contents": contents}
    if OUT_OF_SCOPE in out.get("notes", ""):
        out["notes"] = out["notes"].replace(OUT_OF_SCOPE, POOL_NOTE if pool else "").strip()
    return out


def check_mapping(mapping: dict, tcgdex: dict[str, set[str]]) -> list[str]:
    """Every subset the mapping names must be a TCGdex set of its region's tree."""
    errors = []
    for key, subsets in mapping["extraSets"].items():
        region, _, set_id = key.partition("/")
        for s in [set_id, *subsets]:
            if s not in tcgdex.get(region, ()):
                errors.append(f"mappings/pack_pools.json: {key} names {s}, which TCGdex does not list")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--cache", default=ROOT / ".cache", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    fetcher = Fetcher(args.cache)
    mapping = json.loads((ROOT / "mappings" / "pack_pools.json").read_text(encoding="utf-8"))
    tcgdex = {region: {s["id"] for s in fetcher.get(f"{TCGDEX_API}/{lang}/sets") or []}
              for region, lang in TCGDEX_LANGUAGE.items()}
    if errors := check_mapping(mapping, tcgdex):
        print("\n".join(errors), file=sys.stderr)
        return 1

    packs = [f for f in load(args.data) if f.data["category"] in PACK_CATEGORIES]
    changed: list[Family] = []
    review, counts = [], {}
    for family in packs:
        pool, why = pool_for(family.data, tcgdex, mapping["extraSets"], mapping["skip"])
        if why:
            review.append({"family": family.data["id"], "region": family.data["region"], "set": family.data["set"],
                           "reason": why})
        else:
            counts[family.data["region"]] = counts.get(family.data["region"], 0) + 1
        updated = with_pool(family.data, pool)
        if updated != family.data:
            changed.append(Family(family.path, updated))

    print(f"{len(packs)} booster packs, {sum(counts.values())} with a pool "
          f"({', '.join(f'{n} {r}' for r, n in sorted(counts.items()))}), {len(review)} skipped, "
          f"{len(changed)} files changed")
    if args.dry_run:
        return 0
    for family in changed:
        family.path.write_text(json.dumps(family.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_path = ROOT / "review" / "pack-pools.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps({"skipped": sorted(review, key=lambda r: r["family"])}, ensure_ascii=False,
                                      indent=1) + "\n", encoding="utf-8")
    errors = validate(load(args.data), args.data)
    if errors:
        print("\n".join(errors[:50]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
