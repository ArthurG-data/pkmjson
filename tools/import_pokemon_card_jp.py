"""Name Japanese releases from pokemon-card.com's product search, the official Japanese product list.

import_tcgplayer.py --category 85 writes each Japanese product with TCGplayer's English listing name. The official
list states the name it was sold under, its release date and its contents. This tool finds the family each official
product is, and gives that family's `ja` release the official name, date and search page as a source:

- a booster pack (拡張パック「…」) is the set's one booster pack family. Its set is the TCGdex set with that name
  and a release date within a week: TCGdex misnames some Japanese sets (SV4a is called レイジングサーフ), and the
  date keeps a wrong name from matching.
- any other product whose name is a TCGdex set (デッキビルドBOX ステラミラクル, スタートデッキ100 …) is that set's
  one family that is not a pack, box or case.

An official product that matches nothing goes to review/pokemon-card-jp.json.

    uv run python tools/import_pokemon_card_jp.py [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
import urllib.parse
from collections import defaultdict
from pathlib import Path

from import_tcgplayer import TCGDEX_API, Fetcher
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
    for product in official_products(fetcher):
        family, why = family_for(product, sets, by_set)
        if family is None:
            review.append({"kind": product["kind"], "title": clean_title(product["productTitle"]),
                           "releaseDate": release_day(product["releaseDate"]), "reason": why})
        else:
            claimed[family.data["id"]].append((family, product))
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
