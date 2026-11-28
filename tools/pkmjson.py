"""Load, validate and flatten pkmjson product families."""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

import net

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "product.schema.json").read_text(encoding="utf-8"))
# TCGdex keeps Japanese, Korean, Chinese, Thai and Indonesian cards in its Asian tree.
ASIA_LANGUAGES = {"ja", "ko", "zh-tw", "zh-cn", "th", "id"}
TCGDEX_API = "https://api.tcgdex.net/v2"
# Random cards: the only products that may carry contents.pool.
PACK_CATEGORIES = ("booster_pack", "sleeved_booster_pack")


SETS = ROOT / "sets" / "sets.json"
SERIES = ROOT / "sets" / "series.json"
SEALED = ROOT / "data" / "sealed"
CARDS = ROOT / "data" / "cards"
UUIDS = ROOT / "data" / "uuids"
REVIEW = ROOT / "review"
MAPPINGS = ROOT / "mappings"
# An asia family whose set id, lowercased, is also an international set id starts with this, so the two trees'
# families never share an id: Japan's SM10 and the international sm10 are different sets.
ASIA_PREFIX = "asia-"


@dataclass(frozen=True)
class Family:
    path: Path
    data: dict


def fold(text: str) -> str:
    """Lowercase, accents and punctuation folded, for comparing names."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def slug(text: str) -> str:
    return fold(text).replace(" ", "-")


def set_prefix(region: str, set_id: str, international: Iterable[str] = ()) -> str:
    """The start of every id of a set's families: the set id lowercased, a "+" spelled out ("SM1+" -> "sm1plus").
    An asia set whose prefix is an international set's (`international` holds those set ids) gets "asia-" in
    front."""
    prefix = set_id.lower().replace("+", "plus")
    return ASIA_PREFIX + prefix if region == "asia" and prefix in {s.lower() for s in international} else prefix


def family_prefix(family: dict) -> str:
    """The set prefix a family's id starts with: its set's, with "asia-" when the id has it."""
    plain = set_prefix(family["region"], family["set"])
    if family["region"] == "asia" and family["id"].startswith(ASIA_PREFIX + plain + "-"):
        return ASIA_PREFIX + plain
    return plain


def is_plain_pack(family: dict) -> bool:
    """A set's own booster pack is named <prefix>-booster-pack or <prefix>-booster. A "3 Card Booster Pack" of the
    same set is another product."""
    return family["category"] == "booster_pack" and \
        re.fullmatch(rf"{re.escape(family_prefix(family))}-booster(?:-pack)?", family["id"]) is not None


def plain_pack(families: Iterable[Family]) -> Family | None:
    """The set's own booster pack among one set's families: the plain one, else the only pack."""
    packs = [f for f in families if f.data["category"] == "booster_pack"]
    plain = [f for f in packs if is_plain_pack(f.data)]
    chosen = plain if len(plain) == 1 else packs
    return chosen[0] if len(chosen) == 1 else None


def dumps(data: object, indent: int = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent) + "\n"


def write_json(path: Path, data: object, indent: int = 2) -> None:
    """Write a data, review or release file atomically, in the layout every file of the repository uses."""
    net.write_atomic(path, dumps(data, indent))


def printing_id(card_id: str, language: str, version: dict) -> str:
    """`<card id>~<language>`, with `~<promo types>[+oversized]` for any version but the plain one."""
    parts = [p["name"] for p in version.get("promoTypes", [])] + (["oversized"] if version.get("oversized") else [])
    return f"{card_id}~{language}" + (f"~{'+'.join(parts)}" if parts else "")


def printings(card: dict) -> list[dict]:
    """The card's printings, one per language and version, each with what its version shares and what its language
    holds of its own. An identifier the language sets to null is one the version has and the language lacks."""
    out = []
    for version in card["versions"]:
        for lang, own in version["printings"].items():
            identifiers = {**version.get("identifiers", {}), **own.get("identifiers", {})}
            printing = {"id": printing_id(card["id"], lang, version), "uuid": own.get("uuid"), "language": lang,
                        "versionKey": version.get("key", "")}
            printing.update({k: version[k] for k in ("promoTypes", "oversized") if k in version})
            printing["finishes"] = own["finishes"] if "finishes" in own else version["finishes"]
            if identifiers := {k: v for k, v in identifiers.items() if v is not None}:
                printing["identifiers"] = identifiers
            out.append(printing)
    return out


def dumps_cards(body: dict) -> str:
    """A data/cards file: its set, then one card per line, so a diff shows which cards changed."""
    head = {k: v for k, v in body.items() if k != "cards"}
    lines = [json.dumps(c, ensure_ascii=False, separators=(",", ":")) for c in body["cards"]]
    return json.dumps(head, ensure_ascii=False)[:-1] + ', "cards": [\n' + ",\n".join(lines) + "\n]}\n"


def write_cards(path: Path, body: dict) -> None:
    net.write_atomic(path, dumps_cards(body))


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def official_set_names(path: Path = SETS) -> dict[tuple[str, str, str], str]:
    """(region, set, language) -> the set's name as printed on its packs, from sets/sets.json. Names that only
    TCGdex gives are left out: they are not always the printed name. So is a language that has a logo but no
    name."""
    if not path.exists():
        return {}
    sets = read_json(path)
    return {(s["region"], s["set"], lang): v["name"] for s in sets.values() for lang, v in s["languages"].items()
            if v.get("name") and "tcgdex.net" not in v.get("source", "")}


def load(data_dir: Path) -> list[Family]:
    """Every product family under data_dir, sorted by path."""
    return [Family(p, read_json(p)) for p in sorted(data_dir.rglob("*.json"))]


def write_family(family: Family) -> None:
    write_json(family.path, family.data)


def _contents_of(family: dict, release: dict) -> dict:
    return release.get("contents", family["contents"])


def pool_of(family: dict, release: dict) -> list[dict]:
    """The sets a booster pack can hold, each with its region spelled out and sorted by (region, set). A release
    that lists its own pool replaces the family's, like the rest of its contents."""
    pool = _contents_of(family, release).get("pool") or family["contents"].get("pool") or []
    return sorted(({"set": p["set"], "region": p.get("region", family["region"])} for p in pool),
                  key=lambda p: (p["region"], p["set"]))


def _pool_errors(family: dict, where: Path) -> list[str]:
    """contents.pool belongs to booster packs, and names each set once (a missing region means the family's)."""
    errors = []
    scopes = [("", family["contents"])] + [(f"{r['language']} ", r["contents"]) for r in family["releases"]
                                           if "contents" in r]
    for label, contents in scopes:
        pool = contents.get("pool")
        if pool is None:
            continue
        if family["category"] not in PACK_CATEGORIES:
            errors.append(f"{where}: {label}contents.pool is only for booster packs, not {family['category']}")
        named = [(p.get("region", family["region"]), p["set"]) for p in pool]
        for dup in sorted({n for n in named if named.count(n) > 1}):
            errors.append(f"{where}: {label}contents.pool names {dup[0]}/{dup[1]} twice")
    return errors


def _where(f: Family, data_dir: Path) -> Path:
    return f.path.relative_to(data_dir)


def _schema_errors(families: list[Family], data_dir: Path) -> list[str]:
    schema = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
    return [f"{_where(f, data_dir)}: {'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
            for f in families for e in schema.iter_errors(f.data)]


def _family_errors(by_id: dict[str, Family], dups: list[str], data_dir: Path, sets: dict | None) -> list[str]:
    """Each id once, each file where its region, set and id say, each id starting with its set's prefix, and each
    set listed in sets/sets.json."""
    errors = list(dups)
    international = {s for (region, s) in ((f.data["region"], f.data["set"]) for f in by_id.values())
                     if region == "international"}
    if sets is not None:
        international |= {s["set"] for s in sets.values() if s["region"] == "international"}
    for fid, f in by_id.items():
        where, d = _where(f, data_dir), f.data
        expected = Path(d["region"], d["set"], f"{fid}.json")
        if where != expected:
            errors.append(f"{where}: should live at {expected}")
        prefix = set_prefix(d["region"], d["set"], international)
        if not fid.startswith(prefix + "-"):
            errors.append(f"{where}: id {fid} should start with {prefix}-, its set's prefix")
        if sets is not None and f"{d['region']}/{d['set']}" not in sets:
            errors.append(f"{where}: set {d['region']}/{d['set']} is not in sets/sets.json: run tools/import_sets.py")
    return errors


def _release_errors(f: Family, where: Path) -> list[str]:
    errors = []
    seen = [r["language"] for r in f.data["releases"]]
    if len(seen) != len(set(seen)):
        errors.append(f"{where}: a language is released twice")
    for release in f.data["releases"]:
        if (release["language"] in ASIA_LANGUAGES) != (f.data["region"] == "asia"):
            errors.append(f"{where}: language {release['language']} does not belong to region {f.data['region']}")
    return errors


def _content_errors(f: Family, where: Path, by_id: dict[str, Family], languages: dict[str, set[str]]) -> list[str]:
    """Nested products exist and are released in the language of the release that holds them, and each product
    is listed once per contents."""
    errors = []
    for release in f.data["releases"]:
        lang = release["language"]
        sealed = _contents_of(f.data, release).get("sealed", [])
        named = [i["product"] for i in sealed]
        for dup in sorted({n for n in named if named.count(n) > 1}):
            errors.append(f"{where}: {lang} lists {dup} twice: give it one count")
        for child in named:
            if child not in by_id:
                errors.append(f"{where}: {lang} contains unknown product {child}")
            elif lang not in languages[child]:
                errors.append(f"{where}: {lang} contains {child}, which has no {lang} release")
    return errors


def _owner_errors(by_id: dict[str, Family], data_dir: Path) -> list[str]:
    """A TCGplayer or Cardmarket product sells one family: two families holding one id are one product filed
    twice, or a wrong id."""
    owners: dict[tuple[str, int], list[str]] = {}
    for fid, f in by_id.items():
        if (cardmarket := (f.data.get("identifiers") or {}).get("cardmarketProductId")) is not None:
            owners.setdefault(("Cardmarket", cardmarket), []).append(fid)
        for pid in {p for r in f.data["releases"] for p in (r.get("identifiers") or {}).get("tcgplayerProductIds", [])}:
            owners.setdefault(("TCGplayer", pid), []).append(fid)
    return [f"{_where(by_id[fids[0]], data_dir)}: {site} product {pid} is also on {', '.join(sorted(fids[1:]))}"
            for (site, pid), fids in sorted(owners.items()) if len(fids) > 1]


def validate(families: Iterable[Family], data_dir: Path, sets: dict | None = None) -> list[str]:
    """Every problem of the product families found offline, as 'path: message'. Empty when they are valid. With
    `sets` (sets/sets.json), each family's set must be in it. The UUIDs are tools/uuids.py's to check."""
    families = list(families)
    errors = _schema_errors(families, data_dir)
    if errors:
        return errors
    by_id: dict[str, Family] = {}
    dups = []
    for f in families:
        if f.data["id"] in by_id:
            dups.append(f"{_where(f, data_dir)}: id {f.data['id']} is also used by "
                        f"{_where(by_id[f.data['id']], data_dir)}")
        by_id[f.data["id"]] = f
    errors += _family_errors(by_id, dups, data_dir, sets)
    languages = {fid: {r["language"] for r in f.data["releases"]} for fid, f in by_id.items()}
    for f in by_id.values():
        where = _where(f, data_dir)
        errors += _release_errors(f, where)
        errors += _content_errors(f, where, by_id, languages)
        errors += _pool_errors(f.data, where)
    errors += _owner_errors(by_id, data_dir)
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
    return net.get_json_or_none(f"{TCGDEX_API}/{language}/cards/{net.quote(card_id)}")


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
                "uuid": r["uuid"],
                "familyUuid": d["uuid"],
                "familyId": d["id"],
                "language": lang,
                "region": d["region"],
                "set": d["set"],
                "category": d["category"],
                "name": r["name"],
                "releaseDate": r.get("releaseDate"),
                "identifiers": {**d.get("identifiers", {}), **r.get("identifiers", {})},
                "contentsStatus": d["contentsStatus"],
                "contents": {
                    "sealed": [{"product": f"{i['product']}:{lang}", "count": i["count"]}
                               for i in contents.get("sealed", [])],
                    "cards": [dict(i) for i in contents.get("cards", [])],
                    "other": [dict(i) for i in contents.get("other", [])],
                },
                "sources": r["sources"],
            }
            if pool := pool_of(d, r):
                entry["contents"]["pool"] = pool
            if "notes" in d:
                entry["notes"] = d["notes"]
            out[f"{d['id']}:{lang}"] = entry
    return dict(sorted(out.items()))


def _schema(name: str) -> dict:
    return read_json(ROOT / "schema" / name)


def file_errors(sets_path: Path = SETS, mappings: Path = MAPPINGS, registry: Path | None = None,
                series_path: Path = SERIES) -> list[str]:
    """sets/sets.json, sets/series.json, the mappings and the UUID registry (data/uuids/) against their schemas."""
    errors = []
    checks = [(sets_path, _schema("sets.schema.json")), (series_path, _schema("series.schema.json"))]
    defs = _schema("mappings.schema.json")
    for name in ("tcgplayer_groups", "cardmarket_sealed", "pack_pools", "tcgdex_renames", "sources"):
        checks.append((mappings / f"{name}.json", {**defs, "$ref": f"#/$defs/{name}"}))
    if registry is not None:
        checks += [(path, _schema("uuids.schema.json")) for path in sorted(registry.glob("*.json"))]
    for path, schema in checks:
        if not path.exists():
            continue
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors += [f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: "
                   f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
                   for e in validator.iter_errors(read_json(path))]
    return errors
