"""Load, validate and flatten pkmjson product families."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "product.schema.json").read_text(encoding="utf-8"))
# TCGdex keeps Japanese, Korean, Chinese, Thai and Indonesian cards in its Asian tree.
ASIA_LANGUAGES = {"ja", "ko", "zh-tw", "zh-cn", "th", "id"}
TCGDEX_API = "https://api.tcgdex.net/v2"


@dataclass(frozen=True)
class Family:
    path: Path
    data: dict


def load(data_dir: Path) -> list[Family]:
    """Every product family under data_dir, sorted by path."""
    return [Family(p, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(data_dir.rglob("*.json"))]


def _contents_of(family: dict, release: dict) -> dict:
    return release.get("contents", family["contents"])


def validate(families: Iterable[Family], data_dir: Path) -> list[str]:
    """Every problem found offline, as 'path: message'. Empty when the data is valid."""
    families = list(families)
    errors: list[str] = []
    schema = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    by_id: dict[str, Family] = {}
    for f in families:
        where = f.path.relative_to(data_dir)
        for e in schema.iter_errors(f.data):
            errors.append(f"{where}: {'/'.join(map(str, e.path)) or '(root)'}: {e.message}")
        if not isinstance(f.data.get("id"), str):
            continue
        fid = f.data["id"]
        if fid in by_id:
            errors.append(f"{where}: id {fid} is also used by {by_id[fid].path.relative_to(data_dir)}")
        by_id[fid] = f
        expected = Path(str(f.data.get("region")), str(f.data.get("set")), f"{fid}.json")
        if where != expected:
            errors.append(f"{where}: should live at {expected}")
    if errors:
        return errors

    languages = {fid: {r["language"] for r in f.data["releases"]} for fid, f in by_id.items()}
    for fid, f in by_id.items():
        where = f.path.relative_to(data_dir)
        seen = [r["language"] for r in f.data["releases"]]
        if len(seen) != len(set(seen)):
            errors.append(f"{where}: a language is released twice")
        for release in f.data["releases"]:
            lang = release["language"]
            if (lang in ASIA_LANGUAGES) != (f.data["region"] == "asia"):
                errors.append(f"{where}: language {lang} does not belong to region {f.data['region']}")
            for item in _contents_of(f.data, release).get("sealed", []):
                child = item["product"]
                if child not in by_id:
                    errors.append(f"{where}: {lang} contains unknown product {child}")
                elif lang not in languages[child]:
                    errors.append(f"{where}: {lang} contains {child}, which has no {lang} release")
    errors += _cycles(by_id, data_dir)
    return errors


def _cycles(by_id: dict[str, Family], data_dir: Path) -> list[str]:
    def children(fid: str) -> set[str]:
        f = by_id[fid].data
        out = {i["product"] for i in f["contents"].get("sealed", [])}
        for r in f["releases"]:
            out |= {i["product"] for i in r.get("contents", {}).get("sealed", [])}
        return out & by_id.keys()

    errors, done = [], set()

    def visit(fid: str, stack: list[str]) -> None:
        if fid in stack:
            loop = " -> ".join(stack[stack.index(fid):] + [fid])
            errors.append(f"{by_id[fid].path.relative_to(data_dir)}: products contain each other: {loop}")
            return
        if fid in done:
            return
        for child in sorted(children(fid)):
            visit(child, stack + [fid])
        done.add(fid)

    for fid in sorted(by_id):
        visit(fid, [])
    return errors


def fetch_tcgdex_card(language: str, card_id: str) -> dict | None:
    """A TCGdex card, or None when TCGdex has no such card."""
    url = f"{TCGDEX_API}/{language}/cards/{urllib.parse.quote(card_id)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def validate_cards(families: Iterable[Family], data_dir: Path,
                   fetch: Callable[[str, str], dict | None] = fetch_tcgdex_card) -> list[str]:
    """Check each card against TCGdex: the card and variant exist, and the TCGplayer and Cardmarket ids match the
    ids TCGdex gives that variant."""
    errors: list[str] = []
    cache: dict[tuple[str, str], dict | None] = {}
    for f in families:
        where = f.path.relative_to(data_dir)
        # English for the international tree, Japanese for the Asian one: variant ids are the same in every language.
        lang = "ja" if f.data["region"] == "asia" else "en"
        items = list(f.data["contents"].get("cards", []))
        for r in f.data["releases"]:
            items += r.get("contents", {}).get("cards", [])
        for item in items:
            key = (lang, item["tcgdexCardId"])
            if key not in cache:
                cache[key] = fetch(*key)
            card = cache[key]
            if card is None:
                errors.append(f"{where}: TCGdex has no card {item['tcgdexCardId']}")
                continue
            variants = {v.get("variantId"): v for v in card.get("variants_detailed") or []}
            variant = variants.get(item["tcgdexVariantId"])
            if variant is None:
                errors.append(f"{where}: {item['tcgdexCardId']} has no variant {item['tcgdexVariantId']}")
                continue
            third = variant.get("thirdParty") or {}
            for ours, theirs in (("tcgplayerProductId", "tcgplayer"), ("cardmarketProductId", "cardmarket")):
                if ours in item and third.get(theirs) is not None and third[theirs] != item[ours]:
                    errors.append(f"{where}: {item['tcgdexCardId']} {ours} is {item[ours]}, TCGdex says {third[theirs]}")
    return errors


def flatten(families: Iterable[Family]) -> dict[str, dict]:
    """One entry per product and language, keyed '<family id>:<language>'. A nested product points at the same
    language's entry."""
    out: dict[str, dict] = {}
    for f in families:
        d = f.data
        for r in d["releases"]:
            lang = r["language"]
            contents = _contents_of(d, r)
            entry = {
                "uuid": f"{d['id']}:{lang}",
                "familyId": d["id"],
                "language": lang,
                "region": d["region"],
                "set": d["set"],
                "category": d["category"],
                "name": r["name"],
                "releaseDate": r.get("releaseDate"),
                "identifiers": r.get("identifiers", {}),
                "contentsStatus": d["contentsStatus"],
                "contents": {
                    "sealed": [{"product": f"{i['product']}:{lang}", "count": i["count"]}
                               for i in contents.get("sealed", [])],
                    "cards": [dict(i) for i in contents.get("cards", [])],
                    "other": [dict(i) for i in contents.get("other", [])],
                },
                "sources": r["sources"],
            }
            if "notes" in d:
                entry["notes"] = d["notes"]
            out[entry["uuid"]] = entry
    return dict(sorted(out.items()))
