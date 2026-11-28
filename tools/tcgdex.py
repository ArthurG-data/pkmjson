"""TCGdex's cards-database, as tools/dump_tcgdex.ts dumps it, and the rules that turn it into sets, cards and
printings.

The rules are AutoMana's (core/repositories/app_integration/tcgdex/tcgdex_build.py), which ported them from the
pokemon_exploration prototype that proved them on all of TCGdex:
- A **card** is one TCGdex card id in one tree (`international/sv08-001`).
- An **oracle** is the gameplay card that all its reprints share. It is grouped by a fingerprint of its English rules
  text, or, for a card with no English text, linked to the one English card with the same language-free
  fingerprint.
- A **printing** is a card in one language and one version. The version is the promo types its variants carry
  (a stamp, a foil pattern, an edition) and whether it is oversized. Each printing lists its finishes (nonfoil,
  holo, reverse-holo) and the TCGdex variant of each.

These functions take and give plain dicts, with no I/O but `load_dump`.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from pkmjson import MAPPINGS, ROOT

DUMP = ROOT / ".cache" / "tcgdex"
FOLDERS = {"data": "international", "data-asia": "asia"}
# TCGplayer sells English singles for the international tree and Japanese ones for the Asian tree. A TCGplayer id
# goes only on the printing in that language.
HOME_LANGUAGE = {"international": "en", "asia": "ja"}
POCKET_SERIE = "tcgp"
# Three finishes, Scryfall style. Metal and lenticular cards take the closest finish, plus a card-stock promo type.
FINISH = {"normal": "nonfoil", "holo": "holo", "reverse": "reverse-holo", "metal": "holo", "lenticular": "nonfoil"}
FINISHES = ("nonfoil", "holo", "reverse-holo")
GENERATED = "generated"
# The rules fields that define a gameplay card. Everything else (set, number, rarity, artist, flavour text,
# regulation mark, variants) can change between reprints of one card.
GAMEPLAY_FIELDS = ["category", "hp", "types", "stage", "suffix", "retreat", "trainerType", "energyType",
                   "weaknesses", "resistances", "dexId"]
TEXT_FIELDS = ["name", "effect", "evolveFrom"]
# Fields data-asia sometimes leaves empty (the Japanese Base Set has no weaknesses).
OPTIONAL_NEUTRAL_FIELDS = ["weaknesses", "resistances", "retreat"]


def region_of(folder: str) -> str:
    return FOLDERS[folder]


def load_dump(path: Path = DUMP) -> tuple[list[dict], list[dict], list[dict]]:
    """(series, sets, cards) as dump_tcgdex.ts wrote them."""
    def rows(name: str) -> list[dict]:
        with (path / f"{name}.jsonl").open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    return rows("series"), rows("sets"), rows("cards")


def load_translations(path: Path = DUMP) -> dict:
    """TCGdex's meta/translations as dump_tcgdex.ts copied them: {language: {enum: {English key: translation}}}."""
    return json.loads((path / "translations.json").read_text(encoding="utf-8"))


def dump_commit(path: Path = DUMP) -> str | None:
    commit = path / "commit.txt"
    return commit.read_text(encoding="utf-8").strip() if commit.exists() else None


# --- oracles ----------------------------------------------------------------------------------------------------


def text(value, lang: str):
    """A translatable field is a {lang: text} dict."""
    return value.get(lang) if isinstance(value, dict) else value


def norm(v):
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v.replace("×", "x").replace("’", "'")).strip().lower()
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)   # damage is 40 in some files and "40" in others
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, dict):
        return {k: norm(x) for k, x in sorted(v.items())}
    return v


def sha1(payload) -> str:
    return hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def gameplay_fields(card: dict, fields: list[str]) -> dict:
    """Normalised rules fields. A weakness printed without a multiplier means x2 (the EX-era convention)."""
    payload = {f: norm(card.get(f)) for f in fields}
    if payload.get("weaknesses"):
        payload["weaknesses"] = [dict(w, value=w.get("value") or "x2") for w in payload["weaknesses"]]
    return payload


def game(card: dict) -> str:
    return "pocket" if card["serie"] == POCKET_SERIE else "tcg"


def fingerprint(card: dict, lang: str) -> str:
    """Gameplay identity, from the rules text in one language."""
    payload = gameplay_fields(card, GAMEPLAY_FIELDS)
    payload.update({f: norm(text(card.get(f), lang)) for f in TEXT_FIELDS})
    payload["attacks"] = [norm({"cost": a.get("cost"), "damage": a.get("damage"),
                                "name": text(a.get("name"), lang), "effect": text(a.get("effect"), lang)})
                          for a in card.get("attacks") or []]
    payload["abilities"] = [norm({"type": a.get("type"), "name": text(a.get("name"), lang),
                                  "effect": text(a.get("effect"), lang)}) for a in card.get("abilities") or []]
    payload.update(game=game(card), lang=lang)
    return sha1(payload)


def neutral_fingerprint(card: dict, core: bool = False) -> str | None:
    """A language-free identity (numbers, types, costs) to link cards with no English text. With core, the fields
    data-asia often leaves empty are ignored. None for anything but a Pokémon with a Pokédex number."""
    if card["category"] != "Pokemon" or not card.get("dexId"):
        return None
    fields = [f for f in GAMEPLAY_FIELDS if not (core and f in OPTIONAL_NEUTRAL_FIELDS)]
    payload = gameplay_fields(card, fields)
    payload["attacks"] = [norm({"cost": a.get("cost"), "damage": a.get("damage")}) for a in card.get("attacks") or []]
    payload["n_abilities"] = len(card.get("abilities") or [])
    return sha1(payload)


def canonical_language(languages: Iterable[str]) -> str:
    languages = list(languages)
    return "en" if "en" in languages else sorted(languages)[0]


def _reprint_key(card: dict, lang: str) -> str:
    """What two reprints of one card always share, in one language: the game, the kind of card, its name, and for a
    Pokémon its stage, HP and the names, costs and damage of its attacks and the names of its abilities. Wording,
    and the fields TCGdex often leaves empty, are left out."""
    payload = {"game": game(card), "category": card["category"], "name": norm(text(card.get("name"), lang)),
               "trainerType": card.get("trainerType"), "energyType": card.get("energyType")}
    if card["category"] == "Pokemon":
        payload.update(stage=card.get("stage"), hp=norm(card.get("hp")), suffix=card.get("suffix"),
                       attacks=[norm({"cost": a.get("cost"), "damage": a.get("damage"),
                                      "name": text(a.get("name"), lang)}) for a in card.get("attacks") or []],
                       abilities=[norm({"type": a.get("type"), "name": text(a.get("name"), lang)})
                                  for a in card.get("abilities") or []])
    return sha1(payload)


SIMILAR = 0.85


# Wording the game changed between eras without changing a card: an older reprint says the one, a newer the other.
REWORDINGS = (("the defending pokémon", "your opponent's active pokémon"),
              ("defending pokémon", "your opponent's active pokémon"),
              ("poké-power", "ability"), ("poké-body", "ability"), ("pokémon power", "ability"))


def _words(value) -> str:
    if not (isinstance(value, str) or value is None):
        return json.dumps(norm(value))
    value = norm(value) or ""
    for old, new in REWORDINGS:
        value = value.replace(old, new)
    return re.sub(r"[^\w ]+", "", value)


def _similar(a, b) -> bool:
    """Two texts say the same thing: equal once punctuation is gone, or close enough to be a rewording."""
    import difflib
    a, b = _words(a), _words(b)
    return a == b or difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= SIMILAR


def _compatible(one: dict, other: dict, lang: str) -> bool:
    """Two cards with one reprint key are reprints of one card: every rules field either side leaves empty is no
    difference, and every text says the same thing."""
    for f in GAMEPLAY_FIELDS:
        a, b = gameplay_fields(one, [f])[f], gameplay_fields(other, [f])[f]
        if a not in (None, [], "") and b not in (None, [], "") and a != b:
            return False
    pairs = [(text(one.get(f), lang), text(other.get(f), lang)) for f in ("effect", "evolveFrom")]
    pairs += [(text(x.get("effect"), lang), text(y.get("effect"), lang))
              for key in ("attacks", "abilities")
              for x, y in zip(one.get(key) or [], other.get(key) or [], strict=False)]
    return all(a in (None, "") or b in (None, "") or _similar(a, b) for a, b in pairs)


def _merge_reprints(cards: list[dict], keys: dict[tuple[str, str], str], lang: str) -> int:
    """Join the fingerprints of reprints of one card that differ only in wording or in a field TCGdex left empty:
    every card of a joined group takes the group's smallest fingerprint. The number of fingerprints joined away."""
    parent: dict[str, str] = {}

    def find(fp: str) -> str:
        while parent.get(fp, fp) != fp:
            fp = parent[fp]
        return fp

    buckets: dict[str, list[dict]] = defaultdict(list)
    for c in cards:
        buckets[_reprint_key(c, lang)].append(c)
    joined = 0
    for bucket in buckets.values():
        firsts = {}
        for c in bucket:   # one card per fingerprint is enough to compare
            firsts.setdefault(keys[c["region"], c["id"]], c)
        group = sorted(firsts.items())
        for i, (fp, card) in enumerate(group):
            for other_fp, other in group[:i]:
                a, b = find(fp), find(other_fp)
                if a != b and _compatible(card, other, lang):
                    parent[max(a, b)] = min(a, b)
                    joined += 1
    for c in cards:
        keys[c["region"], c["id"]] = find(keys[c["region"], c["id"]])
    return joined


def group_cards(cards: list[dict]) -> tuple[dict[tuple[str, str], str], Counter]:
    """{(region, card id): oracle fingerprint} for every card, and how each was grouped. An oracle is one gameplay
    card, whatever its reprints: MTG's oracle id.

    1. A card with English text: the fingerprint of its English rules text.
    2. Reprints of one card whose fingerprints differ only in wording (a full stop, a reworded Pokémon Power) or in a
       field TCGdex left empty on one of them are joined (_merge_reprints). Different cards of one name (two
       Pikachu with other attacks) and a TCG Pocket card and its paper namesake stay apart.
    3. Any other card (Asia-only, French-only...): the one English oracle with the same language-free fingerprint,
       else the fingerprint in its own canonical language, joined like 2 within that language.
    """
    keys: dict[tuple[str, str], str] = {}
    stats: Counter = Counter()
    english = [c for c in cards if canonical_language(c["languages"]) == "en"]
    for c in english:
        keys[c["region"], c["id"]] = fingerprint(c, "en")
    stats["joined reprints"] += _merge_reprints(english, keys, "en")
    full: dict[str, set[str]] = defaultdict(set)
    core: dict[str, set[str]] = defaultdict(set)
    for c in english:
        if nf := neutral_fingerprint(c):
            full[nf].add(keys[c["region"], c["id"]])
            core[neutral_fingerprint(c, core=True)].add(keys[c["region"], c["id"]])
    others: dict[str, list[dict]] = defaultdict(list)
    for c in cards:
        if canonical_language(c["languages"]) == "en":
            continue
        candidates, how = set(), "unmatched"
        if nf := neutral_fingerprint(c):
            candidates, how = full.get(nf, set()), "linked"
            if not candidates and any(c.get(f) is None for f in OPTIONAL_NEUTRAL_FIELDS):
                candidates, how = core.get(neutral_fingerprint(c, core=True), set()), "linked_core"
        if len(candidates) == 1:
            keys[c["region"], c["id"]] = next(iter(candidates))
            stats[how] += 1
        else:
            lang = canonical_language(c["languages"])
            keys[c["region"], c["id"]] = fingerprint(c, lang)
            others[lang].append(c)
            stats["ambiguous" if len(candidates) > 1 else "unmatched"] += 1
    for lang, group in others.items():
        stats["joined reprints"] += _merge_reprints(group, keys, lang)
    return keys, stats


# --- printings --------------------------------------------------------------------------------------------------


def slug(value: str) -> str:
    return re.sub(r"\s+", "-", value.strip().lower())


def load_promo_map(path: Path = MAPPINGS / "promo_types.csv") -> dict[tuple[str, str], tuple[str, str]]:
    """(source, raw TCGdex value) -> (promo type, category), from the curated mappings/promo_types.csv."""
    with path.open(newline="", encoding="utf-8") as fh:
        return {(r["source"], r["value"]): (r["promo_type"], r["category"]) for r in csv.DictReader(fh)}


def detailed_variants(card: dict) -> list[dict] | None:
    """The card's variants, legacy boolean variants rebuilt the way TCGdex's compiler rebuilds them. None when TCGdex
    has no variant data (its API would invent one "normal" variant)."""
    if not card.get("legacyVariants"):
        return card.get("variants")
    flags = card.get("variants")
    if not flags:
        return None
    out = []
    for kind, default in (("normal", True), ("reverse", False), ("holo", False)):
        if flags.get(kind, default):
            out.append({"type": kind, "variantId": GENERATED})
            if flags.get("firstEdition"):
                out.append({"type": kind, "stamp": ["1st-edition"], "variantId": GENERATED})
            if kind == "normal" and flags.get("wPromo"):
                out.append({"type": kind, "stamp": ["w-promo"], "variantId": GENERATED})
    return out


def variant_promo_types(variant: dict, promo_map: dict) -> set[tuple[str, str]]:
    """Every attribute of a TCGdex variant that is not its finish, as (promo type, category) pairs."""
    raw = [("stamp", st) for st in variant.get("stamp") or []]
    raw += [(src, variant[src]) for src in ("subtype", "foil") if variant.get(src)]
    if variant["type"] in ("metal", "lenticular"):
        raw.append(("type", variant["type"]))
    return {promo_map.get((src, value)) or promo_map.get((src, slug(value))) or (slug(value), "uncategorized")
            for src, value in raw}


def version_key(promos: Iterable[str], oversized: bool) -> str:
    """AutoMana's version key: the sorted promo types joined by "+", and "|oversized" for a jumbo card."""
    return "+".join(sorted(promos)) + ("|oversized" if oversized else "")


def versions(card: dict, lang: str, promo_map: dict, stats: Counter | None = None) -> dict[str, dict]:
    """{version key: {"promos", "oversized", "finishes": {finish: first TCGdex variant with it}}} of the card in
    one language. A variant that names its languages is only in those."""
    out: dict[str, dict] = {}
    for v in detailed_variants(card) or []:
        if v.get("languages") and lang not in v["languages"]:
            continue
        if v.get("type") not in FINISH:
            if stats is not None:
                stats["unknown variant type"] += 1
            continue
        found = variant_promo_types(v, promo_map)
        oversized = v.get("size") == "jumbo"
        version = out.setdefault(version_key((n for n, _ in found), oversized),
                                 {"promos": found, "oversized": oversized, "finishes": {}})
        version["finishes"].setdefault(FINISH[v["type"]], v)
    return out


# TCGdex's thirdParty key and the identifiers key it becomes. A CardTrader id names the card in every finish,
# and TCGdex repeats it on each variant.
MARKETPLACES = (("tcgplayer", "tcgplayerProductIds"), ("cardmarket", "cardmarketProductIds"),
                ("cardtrader", "cardtraderIds"))


def marketplace_ids(card: dict, region: str, lang: str, version: dict) -> dict[str, dict[str, int]]:
    """{"tcgplayerProductIds" | "cardmarketProductIds" | "cardtraderIds": {finish: id}} for one printing. A finish of "unknown"
    stands for a printing whose finishes TCGdex does not know.

    A TCGplayer id goes only on the home language's printing. The card-level id names the regular printing, so it
    is never lent to a stamped or special version.
    """
    out: dict[str, dict[str, int]] = {}
    for source, key in MARKETPLACES:
        if source == "tcgplayer" and lang != HOME_LANGUAGE[region]:
            continue
        fallback = (card.get("thirdParty") or {}).get(source) if not version["promos"] else None
        if not version["finishes"]:
            if fallback:
                out[key] = {"unknown": fallback}
            continue
        per_finish = {f: (v.get("thirdParty") or {}).get(source) or fallback for f, v in version["finishes"].items()}
        if per_finish := {f: i for f, i in sorted(per_finish.items()) if i}:
            out[key] = per_finish
    return out
