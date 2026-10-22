"""Write sets/sets.json (each set's official name and logo per language) and name booster packs after their set.

Sources, best first:
- pokemon.com's expansion lists (en, de, it, es, fr), saved by tools/pokemon_com_expansions.js: the name printed on
  the pack, its logo and release date. A US expansion page finds its TCGdex set by English name, and its other
  languages through the page's own language links.
- pokemon-card.com, for Japanese: the name in 「…」 of a booster pack release import_pokemon_card_jp.py named.
- TCGdex, for any language the above leave out: its set name and logo. Each value records where it came from.

Every set's plain booster pack then gets, in each language with an official name, a release named after the set, as
printed on the pack ("Karmesin & Purpur – Stürmische Funken"), citing the expansion page.

    uv run python tools/import_sets.py --expansions .cache/pokemon-com-expansions.json [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from import_pokemon_card_jp import clean_title, key, official_products, pack_name, release_day
from import_pokemon_com import launch_day
from import_tcgplayer import TCGDEX_API, Fetcher, fold
from pkmjson import ROOT, Family, load, validate

POKEMON_COM = "https://www.pokemon.com"
LOCALES = {"en": "us", "de": "de", "it": "it", "es": "es", "fr": "fr"}
TCGDEX_LANGUAGES = {"international": ("en", "de", "it", "es", "fr"), "asia": ("ja",)}
# Series words in front of an expansion's English name: "Scarlet & Violet—Surging Sparks" is TCGdex's "Surging
# Sparks". The base sets keep the series name ("Scarlet & Violet").
SERIES_RE = re.compile(r"^(?:scarlet & violet|sword & shield|sun & moon|xy|black & white|hs|"
                       r"mega evolution|diamond & pearl|platinum|heartgold & soulsilver)\s*[—–-]\s*", re.I)
DATE_WINDOW_DAYS = 45


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("&amp;", "&").strip()


def english_key(name: str) -> str:
    """'Scarlet & Violet—Surging Sparks' and 'EX Team Rocket Returns' as TCGdex names them, folded."""
    name = re.sub(r"^pok[eé]mon tcg:\s*", "", strip_tags(name), flags=re.I)
    return fold(SERIES_RE.sub("", re.sub(r"^EX\s+", "", name)))


def tcgdex_date(fetcher: Fetcher, set_id: str) -> dt.date | None:
    released = (fetcher.get(f"{TCGDEX_API}/en/sets/{set_id}") or {}).get("releaseDate")
    return dt.date.fromisoformat(released) if released else None


def plain_pack(families: list[Family]) -> Family | None:
    """The set's own booster pack: the one with id <set>-booster-pack (or <set>-booster), else the only pack. A
    "3 Card Booster Pack" of the same set is another product."""
    packs = [f for f in families if f.data["category"] == "booster_pack"]
    plain = [f for f in packs if re.fullmatch(rf"{re.escape(f.data['set'].lower().replace('+', 'plus'))}-booster(?:-pack)?",
                                              f.data["id"])]
    chosen = plain if len(plain) == 1 else packs
    return chosen[0] if len(chosen) == 1 else None


def official_sets(expansions: dict, english_sets: dict[str, str], fetcher: Fetcher) -> tuple[dict, list]:
    """{tcgdex set id: {lang: {name, logo, releaseDate, source}}} from pokemon.com, and what matched no set."""
    by_url = {lang: {e["url"].rstrip("/"): e for e in expansions[loc]} for lang, loc in LOCALES.items()}
    by_name: dict[str, list[str]] = {}
    for set_id, name in english_sets.items():
        by_name.setdefault(fold(name), []).append(set_id)
    found, review = {}, []
    for url, us in by_url["en"].items():
        candidates = by_name.get(english_key(us["title"]), [])
        day = launch_day(f"x: {us.get('releaseDate', '')}")
        if day and len(candidates) > 1:
            when = dt.date.fromisoformat(day)
            candidates = [c for c in candidates if (d := tcgdex_date(fetcher, c)) and abs((d - when).days) <= DATE_WINDOW_DAYS]
        if len(candidates) != 1:
            review.append({"page": POKEMON_COM + url, "title": strip_tags(us["title"]), "candidates": candidates})
            continue
        entry = {}
        alternates = (expansions.get("alternates", {}).get(url) or {}).get("alts", {})
        for lang in LOCALES:
            page = us if lang == "en" else by_url[lang].get((alternates.get(lang) or "").rstrip("/"))
            if not page:
                continue
            entry[lang] = {"name": strip_tags(page["title"]), "logo": POKEMON_COM + page["thumbnail"],
                           "source": POKEMON_COM + page["url"].rstrip("/")}
            if (released := launch_day(f"x: {page.get('releaseDate', '')}")):
                entry[lang]["releaseDate"] = released
        found[candidates[0]] = entry
    return found, review


def japanese_images(fetcher: Fetcher, families: list[Family], sets: dict) -> dict[str, str]:
    """pokemon-card.com shows no set logos, but each product's image carries one: the image of the product (pack,
    deck, special set) the set's Japanese release was named from, else of the pack named like the set. Keyed by set
    id."""
    products = [p for p in official_products(fetcher) if p.get("tumbsImg")]
    by_title = {clean_title(p["productTitle"]): "https://www.pokemon-card.com" + p["tumbsImg"] for p in products}
    by_pack = {}
    for p in products:
        if p["kind"] == "expansion" and "デラックス" not in p["productTitle"]:
            by_pack.setdefault(key(pack_name(p["productTitle"])), []).append(p)
    images = {}
    for set_id, brief in sets.items():
        # A name is only trusted with a date: TCGdex calls SV4a by SV3a's name.
        found = [p for p in by_pack.get(key(brief["name"]), [])
                 if brief.get("releaseDate") and release_day(p["releaseDate"])
                 and abs((dt.date.fromisoformat(release_day(p["releaseDate"])) -
                          dt.date.fromisoformat(brief["releaseDate"])).days) <= DATE_WINDOW_DAYS]
        if len(found) == 1:
            images[set_id] = "https://www.pokemon-card.com" + found[0]["tumbsImg"]
    named = {}
    for family in sorted(families, key=lambda f: f.data["category"] != "booster_pack"):
        if family.data["region"] != "asia" or family.data["set"] in named:
            continue
        for release in family.data["releases"]:
            if release["language"] == "ja" and release["name"] in by_title:
                named[family.data["set"]] = by_title[release["name"]]
    return {**images, **named}


def japanese_names(families: list[Family]) -> dict[str, dict]:
    """The set name a booster pack's official Japanese name holds: 拡張パック「ストームエメラルダ」 -> ストームエメラルダ."""
    names = {}
    for family in families:
        if family.data["region"] != "asia" or family.data["category"] != "booster_pack":
            continue
        for release in family.data["releases"]:
            official = [s for s in release.get("sources", []) if "pokemon-card.com" in s]
            if release["language"] == "ja" and official and (m := re.findall(r"「([^」]+)」", release["name"])):
                names[family.data["set"]] = {"name": m[-1], "source": official[0]}
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--expansions", required=True, type=Path,
                        help="JSON saved by tools/pokemon_com_expansions.js")
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--cache", default=ROOT / ".cache", type=Path)
    parser.add_argument("--out", default=ROOT / "sets" / "sets.json", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    fetcher = Fetcher(args.cache, pause=0.3)
    expansions = json.loads(args.expansions.read_text(encoding="utf-8"))
    tcgdex = {lang: {s["id"]: s for s in fetcher.get(f"{TCGDEX_API}/{lang}/sets") or []}
              for langs in TCGDEX_LANGUAGES.values() for lang in langs}

    families = load(args.data)
    official, review = official_sets(expansions, {k: v["name"] for k, v in tcgdex["en"].items()}, fetcher)
    japanese = japanese_names(families)
    by_set: dict[tuple[str, str], list[Family]] = {}
    for family in families:
        by_set.setdefault((family.data["region"], family.data["set"]), []).append(family)

    ja_sets = {}
    for set_id, brief in tcgdex["ja"].items():
        detail = fetcher.get(f"{TCGDEX_API}/ja/sets/{set_id}") or {}
        ja_sets[set_id] = {"name": brief["name"], "releaseDate": detail.get("releaseDate")}
    images = japanese_images(Fetcher(args.cache, pause=1.0), families, ja_sets)
    sets, missing_logo = {}, []
    for (region, set_id), members in sorted(by_set.items()):
        entry = {}
        for lang in TCGDEX_LANGUAGES[region]:
            value = dict((official.get(set_id) or {}).get(lang) or {}) if region == "international" else {}
            brief = tcgdex[lang].get(set_id) or {}
            if region == "asia" and set_id in japanese:
                value = dict(japanese[set_id])
            if not value.get("name") and brief.get("name"):
                value = {"name": brief["name"], "source": f"{TCGDEX_API}/{lang}/sets/{set_id}"}
            if value.get("logo"):
                value["logoSource"] = "pokemon.com"
            elif brief.get("logo"):
                value.update(logo=brief["logo"] + ".png", logoSource="tcgdex")
            elif region == "asia" and set_id in images:
                value.update(logo=images[set_id], logoSource="pokemon-card.com", logoKind="product image")
            if value:
                entry[lang] = value
        # A language without a logo of its own shows another language's (English first), then the set symbol, so
        # every set has one to display.
        donors = sorted((v for v in entry.values() if v.get("logo") and "logoLanguage" not in v),
                        key=lambda v: v is not entry.get("en"))
        symbol = (fetcher.get(f"{TCGDEX_API}/en/sets/{set_id}") or {}).get("symbol") if region == "international" else None
        for lang, value in entry.items():
            if value.get("logo"):
                continue
            if donors:
                donor_lang = next(k for k, v in entry.items() if v is donors[0])
                value.update(logo=donors[0]["logo"], logoSource=donors[0]["logoSource"], logoLanguage=donor_lang)
            elif symbol:
                value.update(logo=symbol + ".png", logoSource="tcgdex", logoKind="symbol")
            else:
                missing_logo.append(f"{region}/{set_id}:{lang}")
        if entry:
            sets[f"{region}/{set_id}"] = {"region": region, "set": set_id, "languages": entry}

    # Each set's plain booster pack takes the set's official name, as printed on the pack.
    renamed, changed = 0, {}
    for (region, set_id), members in by_set.items():
        pack = plain_pack(members)
        names = (official.get(set_id) or {}) if region == "international" else {}
        if pack is None or not names:
            continue
        for release in pack.data["releases"]:
            value = names.get(release["language"])
            if not value or release["name"] == value["name"]:
                continue
            release["name"] = value["name"]
            if value["source"] not in release["sources"]:
                release["sources"].append(value["source"])
            changed[pack.data["id"]] = pack
            renamed += 1

    print(f"{len(sets)} sets, {len(official)} with pokemon.com names, {len(japanese)} with pokemon-card.com names, "
          f"{len(missing_logo)} set languages without a logo, {renamed} booster pack releases renamed, "
          f"{len(review)} pokemon.com expansions matched no set")
    if args.dry_run:
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(sets, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for family in changed.values():
        family.path.write_text(json.dumps(family.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "review" / "sets.json").write_text(
        json.dumps({"unmatched_expansions": review, "missing_logo": missing_logo}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    errors = validate(load(args.data), args.data)
    if errors:
        print("\n".join(errors[:50]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
