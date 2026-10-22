"""Add German, Italian, Spanish and French releases from pokemon.com's product gallery.

Each US product page on pokemon.com links its versions in other languages, and each version states the product's
name as sold there and what it contains. tools/pokemon_com_crawl.js collects those pages from inside a browser (the
site refuses scripted clients) and saves them as JSON; this tool reads that file.

A US page finds its family by English name, as import_pokepedia.py does. A language version becomes that family's
release only when it states as many booster packs as the family holds, so a box sold with other packs in Europe is
reported, not guessed. A release holds the same language's nested booster packs, which get a release named after the
TCGdex set, as the French import does. What matches nothing goes to review/pokemon-com.json.

    uv run python tools/import_pokemon_com.py --crawl pokemon-com.json [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

from import_pokepedia import MARGIN, MIN_SCORE, similarity, tokens
from import_tcgplayer import TCGDEX_API, Fetcher, fold
from pkmjson import ROOT, Family, load, validate

REGION = "international"
LANGUAGES = ("de", "it", "es", "fr")
# Counts written as words ("Dieci buste", "Otto buste"), by language. A word's position is its value; the first
# ("a", "ein", "un") and the second where it is a form of one ("eine", "una", "une") both count 1.
NUMBER_WORDS = {
    "en": "a one two three four five six seven eight nine ten eleven twelve",
    "de": "ein eine zwei drei vier fünf sechs sieben acht neun zehn elf zwölf",
    "it": "un una due tre quattro cinque sei sette otto nove dieci undici dodici",
    "es": "un una dos tres cuatro cinco seis siete ocho nueve diez once doce",
    "fr": "un une deux trois quatre cinq six sept huit neuf dix onze douze",
}
NUMBERS = {lang: {w: max(i, 1) for i, w in enumerate(words.split())} for lang, words in NUMBER_WORDS.items()}
NUMBERS["en"]["an"] = 1
# The word each language's product lists use for a booster pack. "Bustine protettive" are sleeves, not packs.
PACK_WORD = {"en": r"(?:\S+\s+){0,6}?booster\s+packs?", "de": r"(?:\S+\s+){0,2}?booster-?packs?",
             "it": r"(?:\S+\s+){0,2}?buste\b|(?:\S+\s+){0,2}?busta\b", "es": r"(?:\S+\s+){0,2}?(?:sobres?|paquetes?)",
             "fr": r"(?:\S+\s+){0,2}?boosters?"}
PACK_RE = {lang: re.compile(rf"^(\d+|{'|'.join(NUMBERS[lang])})\s+(?:{PACK_WORD[lang]})\b", re.I)
           for lang in PACK_WORD}
PACK_NAME = {"de": "Boosterpack {}", "it": "Busta di espansione {}", "es": "Sobre de mejora {}", "fr": "Booster {}"}
# "Pokémon-Sammelkartenspiel: Top-Trainer-Box ..." -> "Top-Trainer-Box ...": the brand is not the product's name.
BRAND = (r"(?:Pok[ée]mon TCG|Pok[ée]mon[- ]Sammelkartenspiel|GCC Pok[ée]mon|JCC Pok[ée]mon|"
         r"Gioco di Carte Collezionabili Pok[ée]mon|Juego de Cartas Coleccionables Pok[ée]mon)\s*:\s*")
BRAND_RE = re.compile("^" + BRAND, re.I)
# The brand at the end of a name: "... del GCC Pokémon", "... de JCC Pokémon", "... des Pokémon-Sammelkartenspiels".
BRAND_TAIL_RE = re.compile(r"\s+(?:(?:del|de|du|des)\s+(?:GCC|JCC)\s+Pok[ée]mon|des\s+Pok[ée]mon-Sammelkartenspiels)$",
                           re.I)
# Card mechanics a product name can carry; a page and a family must name the same ones ("Melmetal ex Battle Deck" is
# not "V Battle Deck [Melmetal V]").
MECHANICS = {"ex", "v", "vmax", "vstar", "gx", "break", "tag", "team"}
MONTHS = {m: i + 1 for names in (
    "january february march april may june july august september october november december",
    "januar februar märz april mai juni juli august september oktober november dezember",
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre",
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre",
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
) for i, m in enumerate(names.split())}


def product_names(title: str) -> list[str]:
    """The products a page title names, without the brand. One page can show two products under one title
    ('Pokémon TCG: A—X Pokémon TCG: A—Y')."""
    parts = [p.strip(" —-") for p in re.split(BRAND, title, flags=re.I) if p.strip(" —-")]
    return [BRAND_TAIL_RE.sub("", p).strip() for p in parts]


def mechanics(name: str) -> set[str]:
    return set(re.split(r"[^a-z0-9]+", fold(name).replace("-", " "))) & MECHANICS


def launch_day(line: str | None) -> str | None:
    """'Launch: November 08, 2024', 'Data di uscita: 8 novembre 2024', '08.11.2024'; a quarter ('Q4 2024') is no
    day."""
    if not line:
        return None
    text = line.split(":", 1)[-1].lower()
    if (m := re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text)):
        day, month, year = map(int, m.groups())
    elif (m := re.search(r"\b([a-zäéû]+)\s+(\d{1,2}),?\s+(\d{4})\b", text)) and m.group(1) in MONTHS:
        month, day, year = MONTHS[m.group(1)], int(m.group(2)), int(m.group(3))
    elif (m := re.search(r"\b(\d{1,2})\.?\s+(?:de\s+)?([a-zäéû]+)\s+(?:de\s+)?(\d{4})\b", text)) and m.group(2) in MONTHS:
        day, month, year = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))
    else:
        return None
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def stated_packs(items: list[str], language: str) -> int:
    def count(word: str) -> int:
        return int(word) if word.isdigit() else NUMBERS[language][word.lower()]
    return sum(count(m.group(1)) for item in items if (m := PACK_RE[language].match(item)))


class Catalog:
    def __init__(self, families: list[Family]):
        self.families = [f for f in families if f.data["region"] == REGION]
        self.by_id = {f.data["id"]: f for f in self.families}
        # A "[Set of 3]" bundle or a case is several products sold together; pokemon.com shows the single product.
        self.candidates = [f for f in self.families if f.data["category"] != "case"
                           and not re.search(r"\bset of \d+\b", fold(f.data["name"]))]
        self.names = {f.data["id"]: [tokens(n) for n in {f.data["name"]} |
                                     {r["name"] for r in f.data["releases"] if r["language"] == "en"}]
                      for f in self.families}

    def match(self, english_name: str) -> tuple[list[Family], float]:
        """The families an English name is. One page often shows every variant of a product ("True Steel Premium
        Collection" is the [Zacian] and the [Zamazenta] family): variants tied for the best score, in one set and
        with the same name once the [variant] is dropped, all match."""
        wanted, kind = tokens(english_name), mechanics(english_name)
        pool = [f for f in self.candidates if mechanics(f.data["name"]) == kind]
        scored = sorted(((max(similarity(wanted, t) for t in self.names[f.data["id"]]), f) for f in pool),
                        key=lambda t: -t[0])
        if not scored or scored[0][0] < MIN_SCORE:
            return [], scored[0][0] if scored else 0.0
        best = scored[0][0]
        tied = [f for s, f in scored if s == best]
        close = [f for s, f in scored if best - MARGIN < s < best]
        variant_key = {(f.data["set"], fold(re.sub(r"\[[^\]]*\]", "", f.data["name"]))) for f in tied}
        if close or len(variant_key) > 1:
            return [], best
        return tied, best

    def packs_of(self, family: Family) -> int:
        return sum(i["count"] for i in family.data["contents"].get("sealed", [])
                   if (c := self.by_id.get(i["product"])) and c.data["category"] in ("booster_pack", "sleeved_booster_pack"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--crawl", required=True, type=Path, help="JSON saved by tools/pokemon_com_crawl.js")
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--cache", default=ROOT / ".cache", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    crawl = json.loads(args.crawl.read_text(encoding="utf-8"))
    products = crawl.get("products", crawl)
    fetcher = Fetcher(args.cache, pause=0.5)
    set_names = {lang: {s["id"]: s["name"] for s in fetcher.get(f"{TCGDEX_API}/{lang}/sets") or []}
                 for lang in LANGUAGES}

    catalog = Catalog(load(args.data))
    review, added, changed = [], {lang: 0 for lang in LANGUAGES}, {}
    claimed: dict[str, str] = {}
    for path, page in sorted(products.items()):
        us = page.get("us") or {}
        if not us.get("title"):
            continue
        english = product_names(us["title"])
        alts = {lang: alt for lang, alt in (page.get("alt") or {}).items()
                if lang in LANGUAGES and alt.get("status") == 200 and alt.get("title")}
        # The packs the official page states. A page without a list cannot be checked against its versions.
        us_items = us.get("items") or []
        for index, name in enumerate(english):
            families, score = catalog.match(name)
            if not families:
                review.append({"page": path, "title": name, "reason": "no family", "score": round(score, 2)})
                continue
            for family in families:
                if family.data["id"] in claimed:
                    # Two pokemon.com pages for one family: neither page's names are certain.
                    review.append({"page": path, "family": family.data["id"], "reason": "family matched twice",
                                   "other": claimed[family.data["id"]]})
                    continue
                claimed[family.data["id"]] = path
                ours = catalog.packs_of(family)
                reference = stated_packs(us_items, "en") if us_items else ours
                if us_items and ours and reference != ours:
                    review.append({"page": path, "family": family.data["id"],
                                   "reason": "English page states other packs", "stated": reference, "ours": ours})
                    continue
                for lang, alt in alts.items():
                    if any(r["language"] == lang for r in family.data["releases"]):
                        continue
                    names = product_names(alt["title"])
                    if len(names) != len(english):
                        review.append({"page": alt["url"], "family": family.data["id"],
                                       "reason": f"{lang} title names another number of products"})
                        continue
                    stated = stated_packs(alt.get("items") or [], lang)
                    if stated != reference or (reference and not alt.get("items")):
                        review.append({"page": alt["url"], "family": family.data["id"],
                                       "reason": f"{lang} page states other packs", "stated": stated,
                                       "expected": reference})
                        continue
                    release = {"language": lang, "name": names[index]}
                    if (day := launch_day(alt.get("date"))):
                        release["releaseDate"] = day
                    release["sources"] = [alt["url"]]
                    family.data["releases"].append(release)
                    changed[family.data["id"]] = family
                    added[lang] += 1

    # A release holds that language's nested booster packs: give each one it needs a release named after the set.
    for family in list(changed.values()):
        for release in family.data["releases"]:
            if release["language"] not in LANGUAGES:
                continue
            for item in family.data["contents"].get("sealed", []):
                child = catalog.by_id.get(item["product"])
                lang = release["language"]
                if child is None or any(r["language"] == lang for r in child.data["releases"]):
                    continue
                if child.data["category"] == "booster_pack" and child.data["set"] in set_names[lang]:
                    child.data["releases"].append({"language": lang,
                                                   "name": PACK_NAME[lang].format(set_names[lang][child.data["set"]]),
                                                   "sources": [release["sources"][0]]})
                    changed[child.data["id"]] = child
    # A release whose nested products still lack that language cannot stand.
    for family in list(changed.values()):
        kept = []
        for release in family.data["releases"]:
            children = [catalog.by_id.get(i["product"]) for i in family.data["contents"].get("sealed", [])]
            if release["language"] in LANGUAGES and any(
                    c is None or not any(r["language"] == release["language"] for r in c.data["releases"])
                    for c in children):
                review.append({"page": release["sources"][0], "family": family.data["id"],
                               "reason": f"a nested product has no {release['language']} release"})
                added[release["language"]] -= 1
                continue
            kept.append(release)
        family.data["releases"] = kept

    print(f"{len(products)} pokemon.com products, releases added: "
          + ", ".join(f"{lang} {n}" for lang, n in added.items()) + f", {len(review)} to review: "
          + ", ".join(f"{reason} {n}" for reason, n in Counter(r["reason"] for r in review).most_common()))
    if args.dry_run:
        return 0
    for family in changed.values():
        family.path.write_text(json.dumps(family.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "review" / "pokemon-com.json").write_text(json.dumps(review, ensure_ascii=False, indent=1) + "\n",
                                                      encoding="utf-8")
    errors = validate(load(args.data), args.data)
    if errors:
        print("\n".join(errors[:50]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
