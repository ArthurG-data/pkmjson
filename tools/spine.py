"""The card spine as a whole: its checks and the release records built from it.

The spine is sets/series.json, sets/sets.json, data/cards/ and data/sealed/, with the UUIDs data/uuids/ keeps
(uuids.Spine holds it all). This module checks what ties them together, and flattens them into the release files'
records: AllSets, AllCards, AllPrintings and AllProducts.
"""
from __future__ import annotations

from collections import Counter

from jsonschema import Draft202012Validator, FormatChecker

import uuids
from pkmjson import ROOT, flatten, pool_of, printings, read_json

ASSETS = "https://assets.tcgdex.net"


def _schema(name: str) -> dict:
    return read_json(ROOT / "schema" / name)


HOME = {"international": "en", "asia": "ja"}


def printing_index(spine: uuids.Spine) -> dict[tuple[str, str, str, str], dict]:
    """{(region, TCGdex card id, TCGdex variant id, language): printing}: what a product's card item names, in each
    language. An item's variant is the same in every language."""
    out = {}
    for body in spine.cards.values():
        for card in body["cards"]:
            for p in printings(card):
                for variant in (p.get("identifiers") or {}).get("tcgdexVariantIds", {}).values():
                    out[body["region"], card["id"], variant, p["language"]] = p
    return out


def printing_of(index: dict, region: str, item: dict, language: str) -> dict | None:
    """The printing a card item is in a release of this language, else in the tree's home language."""
    card, variant = item["tcgdexCardId"], item["tcgdexVariantId"]
    return index.get((region, card, variant, language)) or index.get((region, card, variant, HOME[region]))


def card_errors(spine: uuids.Spine) -> list[str]:
    """data/cards/ against its schema, and each file, card and printing where and once."""
    errors = []
    schema = Draft202012Validator(_schema("cards.schema.json"), format_checker=FormatChecker())
    seen: Counter = Counter()
    for key, body in sorted(spine.cards.items()):
        where = f"data/cards/{key}.json"
        found = [f"{where}: {e.json_path}: {e.message}" for e in schema.iter_errors(body)]
        errors += found[:20]
        if found:
            continue
        if f"{body['region']}/{body['set']}" != key:
            errors.append(f"{where}: holds {body['region']}/{body['set']}, not {key}")
        if key not in spine.sets:
            errors.append(f"{where}: set {key} is not in sets/sets.json")
        for card in body["cards"]:
            if not card["id"].startswith(f"{body['set']}-"):
                errors.append(f"{where}: card {card['id']} is not of set {body['set']}")
            seen[body["region"], card["id"]] += 1
            ids = [p["id"] for p in printings(card)]
            for dup in sorted({i for i in ids if ids.count(i) > 1}):
                errors.append(f"{where}: printing {dup} twice")
    errors += [f"card {r}/{c} is in data/cards/ {n} times" for (r, c), n in sorted(seen.items()) if n > 1]
    for key, s in sorted(spine.sets.items()):
        if s.get("serie") and f"{s['region']}/{s['serie']}" not in spine.series:
            errors.append(f"sets/sets.json: {key}: serie {s['serie']} is not in sets/series.json")
    return errors


def link_errors(spine: uuids.Spine) -> list[str]:
    """Every card a product holds is a printing of the spine, with the same TCGplayer product, and every set a booster
    pack can hold is a set of the spine."""
    errors = []
    index = printing_index(spine)
    for family in spine.families:
        d = family.data
        where = f"data/sealed/{d['region']}/{d['set']}/{d['id']}.json"
        items = list(d["contents"].get("cards", [])) + [i for r in d["releases"]
                                                         for i in r.get("contents", {}).get("cards", [])]
        for item in items:
            printing = printing_of(index, d["region"], item, HOME[d["region"]])
            if printing is None:
                errors.append(f"{where}: no printing of {d['region']}/{item['tcgdexCardId']} has TCGdex variant "
                              f"{item['tcgdexVariantId']}")
                continue
            tcgplayer = set((printing.get("identifiers") or {}).get("tcgplayerProductIds", {}).values())
            if "tcgplayerProductId" in item and tcgplayer and item["tcgplayerProductId"] not in tcgplayer:
                errors.append(f"{where}: {item['tcgdexCardId']} names TCGplayer product {item['tcgplayerProductId']}, "
                              f"its printing {printing['id']} {sorted(tcgplayer)}")
        for r in d["releases"]:
            for p in pool_of(d, r):
                if f"{p['region']}/{p['set']}" not in spine.sets:
                    errors.append(f"{where}: its pool names {p['region']}/{p['set']}, which is not in sets/sets.json")
    return sorted(set(errors))


def errors(spine: uuids.Spine, registry: dict) -> list[str]:
    """Everything wrong with the spine, its links and its UUIDs."""
    found = card_errors(spine)
    if found:
        return found
    return link_errors(spine) + uuids.errors(spine, registry)


# --- release records ----------------------------------------------------------------------------------------------


def image(region_serie: str, set_id: str, local_id: str, lang: str) -> str:
    return f"{ASSETS}/{lang}/{region_serie}/{set_id}/{local_id}"


def all_sets(spine: uuids.Spine) -> dict[str, dict]:
    """AllSets: each set with its UUID, its series and the series' UUID."""
    out = {}
    for key, s in spine.sets.items():
        entry = dict(s)
        if (serie := spine.series.get(f"{s['region']}/{s.get('serie')}")) is not None:
            entry = {**{k: v for k, v in entry.items() if k != "serie"}, "serie": {"id": s["serie"],
                                                                                 "uuid": serie["uuid"],
                                                                                 "name": serie["name"]}}
        out[key] = entry
    return out


def all_cards_and_printings(spine: uuids.Spine) -> tuple[dict[str, dict], dict[str, dict]]:
    """AllCards, keyed `<region>/<card id>`, and AllPrintings, keyed `<region>/<printing id>`. A card lists its
    printings by key; a printing names its card, set and oracle by UUID and carries its image link."""
    cards, prints = {}, {}
    for body in spine.cards.values():
        region, set_id = body["region"], body["set"]
        s = spine.sets[f"{region}/{set_id}"]
        serie = s.get("serie")
        for card in body["cards"]:
            card_key = f"{region}/{card['id']}"
            flat = [p for p in printings(card)]
            record = {k: v for k, v in card.items() if k not in ("versions", "imageLanguages")}
            record = {"uuid": card["uuid"], "id": card["id"], "region": region, "set": set_id, "setUuid": s["uuid"],
                      **{k: v for k, v in record.items() if k not in ("uuid", "id")},
                      "printings": [f"{region}/{p['id']}" for p in flat]}
            cards[card_key] = record
            images = set(card.get("imageLanguages", []))
            for p in flat:
                printing = {"uuid": p["uuid"], "id": p["id"], "cardUuid": card["uuid"], "oracleId": card["oracleId"],
                            "card": card_key, "region": region, "set": set_id, "setUuid": s["uuid"],
                            "localId": card["localId"], **{k: v for k, v in p.items() if k not in ("uuid", "id")}}
                if p["language"] in images and serie:
                    printing["image"] = image(serie, set_id, card["localId"], p["language"])
                prints[f"{region}/{p['id']}"] = printing
    return cards, prints


def all_products(spine: uuids.Spine) -> dict[str, dict]:
    """AllProducts, with each card item's printing and each pool set's UUID."""
    index = printing_index(spine)
    out = flatten(spine.families)
    for entry in out.values():
        for item in entry["contents"]["cards"]:
            if (p := printing_of(index, entry["region"], item, entry["language"])) is not None:
                item["printing"] = p["uuid"]
        for p in entry["contents"].get("pool", []):
            p["setUuid"] = spine.sets[f"{p['region']}/{p['set']}"]["uuid"]
    return out
