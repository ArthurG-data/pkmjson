"""Name Japanese releases from pokemon-card.com's product search, the official Japanese product list.

import_tcgplayer.py --category 85 writes each Japanese product with TCGplayer's English listing name. The official
list states the name it was sold under, its release date and its contents. This tool finds the family each official
product is, and gives that family's `ja` release the official name, date and search page as a source:

- a booster pack (拡張パック「…」) is the set's one booster pack family. Its set is the TCGdex set with that name
  and a release date within a week: TCGdex misnames some Japanese sets (SV4a is called レイジングサーフ), and the
  date keeps a wrong name from matching.
- any other product whose name is a TCGdex set (デッキビルドBOX ステラミラクル, スタートデッキ100 …) is that set's
  one family that is not a pack, box or case.
- a deck or set with no TCGdex set of its own ("Starter Set ex Eevee ex", filed under SV-P) matches the official
  product that names the same Pokémon, in Japanese (PokéAPI's species names), and the same kind of product.

An official product that matches nothing goes to review/pokemon-card-jp.json.

    uv run python tools/import_pokemon_card_jp.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from import_tcgplayer import TCGDEX_API, Fetcher, fold
from pkmjson import ROOT, Family, load, validate

SEARCH_API = ("https://www.pokemon-card.com/products/resultAPI.php?productType={kind}&dateLowerY=1996&dateLowerM=1"
              "&dateLowerD=1&dateUpperY=2030&dateUpperM=12&dateUpperD=31&page={page}")
SEARCH_PAGE = "https://www.pokemon-card.com/products/index.html?"
KINDS = ("expansion", "construction", "others")   # "peripheral" is sleeves, deck boxes and other goods
LANGUAGE = "ja"
DATE_WINDOW_DAYS = 7
# Product-type words in front of a pack's name, in official titles and in TCGdex set names alike.
PREFIX_RE = re.compile(r"^(?:第\d+弾)?(?:基本)?(?:強化)?(?:拡張|ハイクラス|コンセプト|スペシャル|プレミアムチャンピオン)?パック"
                       r"(?:ex\d+)?")
ROLES_NOT_OWN_SET = {"booster_pack", "booster_box", "case"}
SPECIES_CSV = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_species_names.csv"
ENGLISH_ID, JAPANESE_ID = "9", "1"   # PokéAPI language ids: English, Japanese (kana)
# The kind of product, as a TCGplayer name and an official Japanese title write it. Longest first.
KIND_WORDS = [
    ("battle master deck", "バトルマスターデッキ"), ("premium deck set", "プレミアムデッキセット"),
    ("special deck set", "スペシャルデッキセット"), ("deck build box", "デッキビルドBOX"),
    ("starter set", "スターターセット"), ("start deck", "スタートデッキ"), ("special box", "スペシャルBOX"),
    ("premium trainer box", "プレミアムトレーナーボックス"), ("battle academy", "バトルアカデミー"),
]


def clean_title(title: str) -> str:
    """'拡張パック「スカーレット<big>ex</big >」' -> '拡張パック「スカーレットex」'."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", title)).strip()


def key(name: str) -> str:
    """A name reduced for comparing: width folded, readings ('（イチゴーイチ）'), product-type words, spaces and
    punctuation dropped."""
    name = unicodedata.normalize("NFKC", clean_title(name))
    name = re.sub(r"[(（][ぁ-んァ-ヶー]+[)）]", "", name)
    name = re.sub(r"[\s・「」『』\"'!?〜~ー\-:：&＆]", "", name)
    return PREFIX_RE.sub("", name.lower())


def pack_name(title: str) -> str:
    """The expansion an official pack title names: the last 「…」, else the title itself."""
    quoted = re.findall(r"「([^」]+)」", clean_title(title))
    return quoted[-1] if quoted else title


def release_day(text: str) -> str | None:
    found = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text or "")
    return dt.date(*map(int, found.groups())).isoformat() if found else None


def search_page(kind: str, title: str) -> str:
    return SEARCH_PAGE + urllib.parse.urlencode({"productType": kind, "keyword": pack_name(title)})


def official_products(fetcher: Fetcher) -> list[dict]:
    products = []
    for kind in KINDS:
        page, pages = 1, 1
        while page <= pages:
            body = fetcher.get(SEARCH_API.format(kind=kind, page=page)) or {}
            pages = body.get("maxPage", 0)
            products += [{**p, "kind": kind} for p in body.get("products") or []]
            page += 1
    return products


class SetIndex:
    """TCGdex Japanese sets by reduced name, each with its release date."""

    def __init__(self, fetcher: Fetcher):
        self.by_key: dict[str, list[tuple[str, dt.date | None]]] = defaultdict(list)
        for brief in fetcher.get(f"{TCGDEX_API}/ja/sets") or []:
            detail = fetcher.get(f"{TCGDEX_API}/ja/sets/{brief['id']}") or {}
            released = detail.get("releaseDate")
            self.by_key[key(brief["name"])].append(
                (brief["id"], dt.date.fromisoformat(released) if released else None))

    def find(self, name: str, day: str | None) -> str | None:
        """The one set with this name released within a week of `day`."""
        if not day:
            return None
        when = dt.date.fromisoformat(day)
        found = [sid for sid, released in self.by_key.get(key(name), [])
                 if released and abs((released - when).days) <= DATE_WINDOW_DAYS]
        return found[0] if len(found) == 1 else None


def family_for(product: dict, sets: SetIndex, by_set: dict[str, list[Family]]) -> tuple[Family | None, str]:
    """The family an official product is, or None and why not."""
    title, day = product["productTitle"], release_day(product["releaseDate"])
    if product["kind"] == "expansion":
        if "デラックス" in title:
            return None, "deluxe pack set"
        set_id = sets.find(pack_name(title), day)
        role = {"booster_pack"}
    else:
        set_id = sets.find(title, day)
        role = None
    if set_id is None:
        return None, "no TCGdex set with this name and date"
    families = [f for f in by_set.get(set_id, [])
                if (f.data["category"] in role if role else f.data["category"] not in ROLES_NOT_OWN_SET)]
    if len(families) != 1:
        return None, f"{len(families)} families in {set_id}"
    return families[0], ""


def species_names(fetcher: Fetcher) -> dict[str, str]:
    """English Pokémon species name (folded) -> its Japanese name, from PokéAPI's species names table."""
    path = fetcher.cache / "pokeapi_pokemon_species_names.csv"
    if not path.exists():
        request = urllib.request.Request(SPECIES_CSV, headers={"User-Agent": "pkmjson/0.1"})
        path.write_bytes(urllib.request.urlopen(request, timeout=60).read())
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    by_id = defaultdict(dict)
    for row in rows:
        by_id[row["pokemon_species_id"]][row["local_language_id"]] = row["name"]
    return {fold(names[ENGLISH_ID]): names[JAPANESE_ID] for names in by_id.values()
            if ENGLISH_ID in names and JAPANESE_ID in names}


def pokemon_matches(families: list[Family], products: list[dict], species: dict[str, str]) -> list[tuple[Family, dict]]:
    """Families and official products that name the same Pokémon and the same kind of product. Every Pokémon the
    English name holds must appear, in Japanese, in the official title, and so must the kind ("Starter Set" is
    スターターセット). One family to one product only: anything matching twice is left out."""
    names = sorted(species, key=len, reverse=True)
    pairs = []
    for family in families:
        english = fold(family.data["name"])
        found, rest = [], f" {english} "
        for name in names:
            if f" {name} " in rest:
                found.append(species[name])
                rest = rest.replace(f" {name} ", " ")
        kinds = [ja for en, ja in KIND_WORDS if f" {en} " in f" {english} "]
        if not found or not kinds:
            continue
        hits = [p for p in products if all(key(n) in key(p["productTitle"]) for n in found)
                and key(kinds[0]) in key(p["productTitle"])]
        if len(hits) == 1:
            pairs.append((family, hits[0]))
    per_product = defaultdict(list)
    for family, product in pairs:
        per_product[id(product)].append(family)
    return [(f, p) for f, p in pairs if len(per_product[id(p)]) == 1]


def name_release(family: Family, product: dict) -> bool:
    """Give the family's ja release the official name, date and source. False when it already has them."""
    release = next(r for r in family.data["releases"] if r["language"] == LANGUAGE)
    source = search_page(product["kind"], product["productTitle"])
    named = {**release, "name": clean_title(product["productTitle"]),
             "sources": release["sources"][:1] + [source]}
    if (day := release_day(product["releaseDate"])):
        named["releaseDate"] = day
    named = {k: named[k] for k in ("language", "name", "releaseDate", "identifiers", "sources") if k in named}
    if named == release:
        return False
    family.data["releases"] = [named if r is release else r for r in family.data["releases"]]
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--cache", default=ROOT / ".cache", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    fetcher = Fetcher(args.cache, pause=1.0)

    by_set: dict[str, list[Family]] = defaultdict(list)
    for family in load(args.data):
        if family.data["region"] == "asia" and any(r["language"] == LANGUAGE for r in family.data["releases"]):
            by_set[family.data["set"]].append(family)
    sets = SetIndex(fetcher)
    changed, claimed, review = {}, defaultdict(list), []
    official = official_products(fetcher)
    unplaced = []
    for product in official:
        family, why = family_for(product, sets, by_set)
        if family is None:
            unplaced.append((product, why))
        else:
            claimed[family.data["id"]].append((family, product))
    # Decks and sets with no TCGdex set of their own ("Starter Set ex Eevee ex" under SV-P) match by the Pokémon
    # they are named after and the kind of product.
    taken = set(claimed)
    unnamed = [f for families in by_set.values() for f in families if f.data["id"] not in taken
               and f.data["category"] not in ROLES_NOT_OWN_SET]
    by_pokemon = pokemon_matches(unnamed, [p for p, _ in unplaced if p["kind"] != "expansion"], species_names(fetcher))
    for family, product in by_pokemon:
        claimed[family.data["id"]].append((family, product))
    placed = {id(p) for _, p in by_pokemon}
    review += [{"kind": p["kind"], "title": clean_title(p["productTitle"]), "releaseDate": release_day(p["releaseDate"]),
                "reason": why} for p, why in unplaced if id(p) not in placed]
    for fid, matches in claimed.items():
        if len(matches) > 1:
            # Two official products for one family (a reprint, a re-release): neither name is certain.
            review += [{"kind": p["kind"], "title": clean_title(p["productTitle"]), "family": fid,
                        "reason": "several official products match this family"} for _, p in matches]
            continue
        family, product = matches[0]
        if name_release(family, product):
            changed[fid] = family

    print(f"{sum(len(m) == 1 for m in claimed.values())} families named, {len(changed)} changed, "
          f"{len(review)} official products to review")
    if args.dry_run:
        return 0
    for family in changed.values():
        family.path.write_text(json.dumps(family.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_path = ROOT / "review" / "pokemon-card-jp.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    errors = validate(load(args.data), args.data)
    if errors:
        print("\n".join(errors[:50]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
