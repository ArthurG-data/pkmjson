"""Write the card spine from TCGdex's cards-database: the series, the sets' TCGdex facts and every card and printing.

    tools/sync_tcgdex.sh                         # dump the pinned commit to .cache/tcgdex/ first
    uv run python tools/import_tcgdex.py [--dump .cache/tcgdex] [--dry-run]

It writes:
- sets/series.json: every TCGdex series, keyed `<region>/<serie>`, with its name per language;
- sets/sets.json: in every set's entry, the keys this tool owns (`serie`, `identifiers` and `tcgdex`). The other
  keys are kept: `languages` is import_sets.py's, `uuid` is uuids.py's. A TCGdex set sets.json lacks is added.
- data/cards/<region>/<set>.json: the set's cards, each with its printings (see tools/tcgdex.py for the rules);
- data/translations.json: TCGdex's meta/translations, the word its API shows for each English enum value.

Every UUID is kept or given by tools/uuids.py before anything is written. The repository's placeholders do not
make it in, and review/tcgdex.json says why: a set file that declares another file's set id, and the cards filed
under it.

A set's TCGplayer groups are the ones TCGdex names and the ones mappings/tcgplayer_groups.json ties to it.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import tcgdex
import uuids
from pkmjson import CARDS, MAPPINGS, REVIEW, SERIES, SETS, TRANSLATIONS, read_json, write_cards, write_json

# The card fields kept as TCGdex states them, in this order. A card's set, number and variants become the record's
# own keys and its printings.
CARD_FIELDS = ("category", "name", "rarity", "illustrator", "regulationMark", "hp", "types", "stage", "suffix",
               "evolveFrom", "retreat", "trainerType", "energyType", "dexId", "cameoDexIds", "effect", "description",
               "item", "attacks", "abilities", "weaknesses", "resistances", "boosters", "legal", "banned")


def serie_key(serie: dict) -> str:
    """A serie's id. A placeholder whose id is 'null' goes by its file name."""
    return serie["file"] if serie["id"] == "null" else serie["id"]


def kept_sets(sets: list[dict]) -> tuple[dict[tuple[str, str], dict], list[dict]]:
    """{(region, set id): set} with each id once, and the placeholders left out. Of several files declaring one id,
    the file named like the id is the set's; else the first by file name."""
    by_id: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for s in sets:
        by_id[tcgdex.region_of(s["folder"]), s["id"]].append(s)
    kept, review = {}, []
    for key, found in sorted(by_id.items()):
        found = sorted(found, key=lambda s: (s["file"] != s["id"], s["file"]))
        kept[key] = found[0]
        review += [{"region": key[0], "set": key[1], "file": s["file"],
                    "reason": f"declares the id of {found[0]['file']}"} for s in found[1:]]
    return kept, review


def grouped_versions(card: dict, region: str, promo_map: dict, stats: Counter,
                     set_stamp: str | None = None) -> list[dict]:
    """The card's versions, each with its printings by language.

    A version holds what its printings share: promo types, oversize, finishes and the TCGdex, Cardmarket and
    CardTrader ids of each finish. Each language holds its own TCGplayer ids, the home language's only, and whatever differs from the
    version, which is a variant TCGdex marks as printed in some languages only. pkmjson.printings() lays them out
    one printing per language and version again.
    """
    per_key: dict[str, dict[str, dict]] = {}
    for lang in card["languages"]:
        found = tcgdex.versions(card, lang, promo_map, stats, set_stamp)
        known = bool(found)
        if not found:
            found = {"": {"promos": set(), "oversized": False, "finishes": {}}}
        for key, version in found.items():
            ids = tcgdex.marketplace_ids(card, region, lang, version)
            facts = {"finishes": [f for f in tcgdex.FINISHES if f in version["finishes"]] if known else None}
            shared = {}
            if variants := {f: v["variantId"] for f, v in sorted(version["finishes"].items())
                            if v.get("variantId") and v["variantId"] != tcgdex.GENERATED}:
                shared["tcgdexVariantIds"] = variants
            shared.update({k: ids[k] for k in ("cardmarketProductIds", "cardtraderIds") if k in ids})
            facts["identifiers"] = shared
            facts["own"] = {k: v for k, v in ids.items() if k == "tcgplayerProductIds"}
            facts["version"] = version
            per_key.setdefault(key, {})[lang] = facts
    out = []
    for key, langs in sorted(per_key.items()):
        # What most of the languages have is the version's; the others say how they differ.
        common = Counter(json.dumps([f["finishes"], f["identifiers"]], sort_keys=True) for f in langs.values())
        finishes, identifiers = json.loads(common.most_common(1)[0][0])
        version = next(iter(langs.values()))["version"]
        entry: dict = {}
        if key:
            entry["key"] = key
        if version["promos"]:
            entry["promoTypes"] = [{"name": n, "category": c} for n, c in sorted(version["promos"])]
        if version["oversized"]:
            entry["oversized"] = True
        # TCGdex knows no variant of the card: its finishes are not known, not none.
        entry["finishes"] = finishes
        if identifiers:
            entry["identifiers"] = identifiers
        printings = {}
        for lang, facts in langs.items():
            own: dict = {}
            if facts["finishes"] != finishes:
                own["finishes"] = facts["finishes"]
            ids = {k: v for k, v in facts["identifiers"].items() if identifiers.get(k) != v}
            ids.update({k: None for k in identifiers if k not in facts["identifiers"]})
            ids.update(facts["own"])
            if ids:
                own["identifiers"] = ids
            printings[lang] = own
        entry["printings"] = printings
        out.append(entry)
    return out


def card_record(card: dict, region: str, promo_map: dict, stats: Counter, set_stamp: str | None = None) -> dict:
    record = {"id": card["id"], "localId": card["localId"]}
    # Kept exactly as TCGdex has them, an empty list included: the oracle fingerprint reads them.
    record.update({k: card[k] for k in CARD_FIELDS if k in card})
    # The languages TCGdex has an image in. The image is https://assets.tcgdex.net/<language>/<serie>/<set>/<number>.
    if images := [lang for lang in card["languages"] if lang in (card.get("images") or {})]:
        record["imageLanguages"] = images
    record["versions"] = grouped_versions(card, region, promo_map, stats, set_stamp)
    return record


def set_entry(previous: dict | None, s: dict, region: str, groups: list[int]) -> dict:
    """A set's sets.json entry: the keys this tool owns, from TCGdex, and the others kept from `previous`."""
    third = s.get("thirdParty") or {}
    identifiers = {}
    if ids := sorted({*groups, *([third["tcgplayer"]] if third.get("tcgplayer") else [])}):
        identifiers["tcgplayerGroupIds"] = ids
    if third.get("cardmarket"):
        identifiers["cardmarketExpansionIds"] = [third["cardmarket"]]
    facts = {"name": s["name"], "releaseDate": s["releaseDate"], "cardCount": s["cardCount"]}
    facts.update({k: s[k] for k in ("abbreviations", "tcgOnline", "logos", "symbol") if s.get(k)})
    entry = {"region": region, "set": s["id"]}
    if previous and "uuid" in previous:
        entry["uuid"] = previous["uuid"]
    entry["serie"] = s["serie"] if s["serie"] != "null" else s["serieFile"]
    if identifiers:
        entry["identifiers"] = identifiers
    entry["tcgdex"] = facts
    entry["languages"] = (previous or {}).get("languages", {})
    return entry


def set_stamp_errors(set_stamps: dict[tuple[str, str], str], kept: dict, promo_map: dict) -> list[str]:
    """What is wrong with mappings/set_stamps.json: a set TCGdex does not list, or a stamp that is no promo type."""
    known = {name for name, _ in promo_map.values()}
    errors = [f"mappings/set_stamps.json names {region}/{set_id}, which TCGdex does not list"
              for region, set_id in sorted(set_stamps) if (region, set_id) not in kept]
    errors += [f"mappings/set_stamps.json gives {region}/{set_id} {name}, which is no promo type of "
               "mappings/promo_types.csv" for (region, set_id), name in sorted(set_stamps.items()) if name not in known]
    return errors


def build(dump: Path, sets_path: Path, groups: dict[tuple[str, str], list[int]]):
    """(series, sets, card files {(region, set): body}, review, stats) from a dump, sets.json as it is, and the
    TCGplayer groups the mapping ties to each set."""
    raw_series, raw_sets, raw_cards = tcgdex.load_dump(dump)
    promo_map = tcgdex.load_promo_map()
    set_stamps = tcgdex.load_set_stamps()
    stats: Counter = Counter()
    series = {}
    for s in sorted(raw_series, key=lambda s: (s["folder"], serie_key(s))):
        region = tcgdex.region_of(s["folder"])
        series[f"{region}/{serie_key(s)}"] = {"region": region, "serie": serie_key(s), "name": s["name"]}
    kept, review = kept_sets(raw_sets)
    if errors := set_stamp_errors(set_stamps, kept, promo_map):
        raise SystemExit("\n".join(errors))
    previous = read_json(sets_path) if sets_path.exists() else {}
    sets = dict(previous)
    for (region, set_id), s in kept.items():
        key = f"{region}/{set_id}"
        sets[key] = set_entry(previous.get(key), s, region, groups.get((region, set_id), []))
    sets = dict(sorted(sets.items()))
    files: dict[tuple[str, str], dict] = {}
    seen: set[tuple[str, str]] = set()
    for card in sorted(raw_cards, key=lambda c: (c["folder"], c["set"], c["setFile"], c["id"])):
        region = tcgdex.region_of(card["folder"])
        home = kept.get((region, card["set"]))
        if home is None or card["setFile"] != home["file"]:
            review.append({"region": region, "card": card["id"], "file": card["setFile"],
                           "reason": "filed under a set file that declares another file's set id"})
            continue
        if not card["languages"]:
            review.append({"region": region, "card": card["id"],
                           "reason": "named in no language its set is published in"})
            continue
        if (region, card["id"]) in seen:
            review.append({"region": region, "card": card["id"], "reason": "card id listed twice"})
            continue
        seen.add((region, card["id"]))
        body = files.setdefault((region, card["set"]), {"region": region, "set": card["set"], "cards": []})
        body["cards"].append(card_record(card, region, promo_map, stats, set_stamps.get((region, card["set"]))))
    for body in files.values():
        body["cards"].sort(key=lambda c: natural(c["localId"]))
    stats["cards"] = len(seen)
    stats["printings"] = sum(len(v["printings"]) for b in files.values() for c in b["cards"] for v in c["versions"])
    return series, sets, files, review, stats


def natural(local_id: str) -> tuple:
    """'2' before '10', and 'SWSH020' after 'SWSH019': the digits of a number compare as numbers."""
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in __import__("re").findall(r"\d+|\D+", local_id))


def mapped_groups(path: Path = MAPPINGS / "tcgplayer_groups.json") -> dict[tuple[str, str], list[int]]:
    out: dict[tuple[str, str], list[int]] = defaultdict(list)
    for m in read_json(path):
        out[m["region"], m["set"]].append(m["groupId"])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dump", default=tcgdex.DUMP, type=Path)
    parser.add_argument("--sets", default=SETS, type=Path)
    parser.add_argument("--series", default=SERIES, type=Path)
    parser.add_argument("--cards", default=CARDS, type=Path)
    parser.add_argument("--review", default=REVIEW, type=Path)
    parser.add_argument("--translations", default=TRANSLATIONS, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not (args.dump / "cards.jsonl").exists():
        print(f"no TCGdex dump in {args.dump}: run tools/sync_tcgdex.sh", file=sys.stderr)
        return 1
    series, sets, files, review, stats = build(args.dump, args.sets, mapped_groups())
    print(f"{len(series)} series, {len(sets)} sets, {stats['cards']} cards, {stats['printings']} printings, "
          f"{len(review)} to review")
    if args.dry_run:
        return 0
    previous = uuids.Spine.load()
    spine = uuids.Spine.load()
    spine.series, spine.sets = series, sets
    spine.cards = {f"{r}/{s}": body for (r, s), body in files.items()}
    try:
        spine.stamp(previous)
    except uuids.Conflict as error:
        print(error, file=sys.stderr)
        return 1
    write_json(args.series, spine.series, indent=1)
    write_json(args.sets, spine.sets, indent=1)
    stale = {p for p in args.cards.rglob("*.json")}
    for key, body in spine.cards.items():
        path = args.cards / f"{key}.json"
        write_cards(path, body)
        stale.discard(path)
    for path in stale:
        path.unlink()
    write_json(args.review / "tcgdex.json", review, indent=1)
    write_json(args.translations, tcgdex.load_translations(args.dump), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
