"""Generate product families from TCGplayer's sealed products (via tcgcsv.com) and their official contents text.

TCGplayer prints each product's official contents list in its CardText. This tool turns that list into pkmjson
contents: booster packs and boxes become nested products, promo cards are pinned to a TCGdex card and variant
through TCGplayer's promo listings, and everything else becomes an `other` item. A product whose text cannot be
fully resolved is written as `partial`, and what was left over goes to review/tcgplayer-<category>.json.

A file this tool wrote cites only the TCGplayer product page, and a re-run rewrites it. A file with any other
source was written by hand and is never touched; its TCGplayer ids still anchor nested products.

    uv run python tools/import_tcgplayer.py [--group 23651] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from pkmjson import ROOT, Family, load, validate

TCGCSV = "https://tcgcsv.com/tcgplayer"
TCGDEX_API = "https://api.tcgdex.net/v2"
CATEGORY = 3  # Pokémon, English. Japanese (85) has no contents text.
REGION = "international"
LANGUAGE = "en"
USER_AGENT = "pkmjson/0.1 (+https://github.com/ArthurG-data/pkmjson)"
PROMO_WINDOW_DAYS = 45
PACKS = ("booster_pack", "sleeved_booster_pack")  # random cards: never complete
SERIES_PREFIX = r"^(?:xy|sm|sun moon|swsh|sword shield|sv|scarlet violet|bw|black white|me|mega evolution|hgss|dp)\b"

NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "eighteen": 18, "thirty-six": 36}
COUNT = r"(\d+|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"

# (category, name pattern), first match wins. Order matters: a case before the box it holds.
CATEGORY_RULES = [
    ("case", r"\bcase\b|\bdisplay\b"),
    ("other", r"\bset of \d+\b|\bart bundle\b|\bfun pack\b"),
    ("half_booster_box", r"half booster box"),
    ("booster_box", r"booster box"),
    ("elite_trainer_box", r"elite trainer box|\betb\b"),
    ("booster_bundle", r"booster bundle"),
    ("build_and_battle_box", r"build (?:and )?battle box"),
    ("sleeved_booster_pack", r"sleeved booster"),
    ("blister", r"blister|checklane"),
    ("booster_pack", r"booster pack|\bbooster\b$"),
    ("tin", r"\btin\b"),
    ("premium_collection", r"premium collection|ultra[- ]premium"),
    ("collection_box", r"collection|\bbox\b"),
    ("theme_deck", r"theme deck"),
    ("battle_deck", r"battle deck|league battle deck|deck"),
]


# --- fetching ---------------------------------------------------------------------------------------------------


class Fetcher:
    """GETs JSON, cached on disk so a re-run does not refetch."""

    def __init__(self, cache: Path, pause: float = 0.2):
        self.cache, self.pause = cache, pause

    def get(self, url: str) -> dict | list | None:
        path = self.cache / re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[1])
        if path.exists():
            body = json.loads(path.read_text(encoding="utf-8"))
            return None if body == {"__missing__": True} else body
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        for attempt in range(6):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    body = {"__missing__": True}
                    break
                if error.code not in (429, 500, 502, 503, 504) or attempt == 5:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == 5:
                    raise
            time.sleep(2 ** attempt)
        time.sleep(self.pause)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return None if body == {"__missing__": True} else body


def _results(body) -> list[dict]:
    if isinstance(body, dict):
        return body.get("results") or []
    return body or []


# --- text helpers -----------------------------------------------------------------------------------------------


def fold(text: str) -> str:
    """Lowercase, accents and punctuation folded, for comparing names."""
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def slug(text: str) -> str:
    return fold(text).replace(" ", "-")


def count_of(word: str) -> int:
    return int(word) if word.isdigit() else NUMBER_WORDS[word.lower()]


def text_parts(card_text: str) -> list[tuple[bool, str]]:
    """The non-empty lines of a product's CardText, tags stripped, each with whether it is a bullet."""
    text = html.unescape(card_text or "").replace("\r", "")
    parts = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p)).strip()
             for p in re.split(r"<br\s*/?>|<li>|</li>|<p>|</p>|\n", text)]
    out = []
    for part in parts:
        bullet = part[:1] in "•-*·"
        part = part.lstrip("•-*· ").strip() if bullet else part
        if len(part) > 1:
            out.append((bullet, part))
    return out


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!])\s+", text) if s.strip()]


# A case's unit, by the words its text uses, checked in order: sleeved packs before packs.
CASE_UNITS = [
    (r"sleeved booster packs?", "sleeved_booster_pack"),
    (r"(?:booster |display )box(?:es)?|displays", "booster_box"),
    (r"elite trainer box(?:es)?", "elite_trainer_box"),
    (r"booster bundles?", "booster_bundle"),
    (r"build (?:and )?battle box(?:es)?", "build_and_battle_box"),
    (r"booster packs?", "booster_pack"),
]


def classify(name: str) -> str:
    folded = fold(name)
    for category, pattern in CATEGORY_RULES:
        if re.search(pattern, folded):
            return category
    return "other"


def is_sealed(product: dict) -> bool:
    """Not a single card, and not a 'Code Card - ...' listing (a digital code TCGplayer sells on its own)."""
    names = {e.get("name") for e in product.get("extendedData") or []}
    return not names & {"Number", "Rarity"} and not fold(product.get("name", "")).startswith("code card")


def card_text(product: dict) -> str:
    return next((e.get("value") or "" for e in product.get("extendedData") or [] if e.get("name") == "CardText"), "")


def release_date(product: dict) -> str | None:
    released = (product.get("presaleInfo") or {}).get("releasedOn")
    return released[:10] if released else None


# --- model ------------------------------------------------------------------------------------------------------


@dataclass
class Group:
    group_id: int
    set_id: str
    name: str          # TCGplayer's group name, e.g. "SV08: Surging Sparks"
    expansion: str     # the name products use, folded, e.g. "surging sparks"
    published: str | None = None
    serie: str | None = None   # TCGdex serie id, e.g. "sv"
    products: list[dict] = field(default_factory=list)


@dataclass
class Draft:
    product: dict
    group: Group
    family_id: str
    category: str
    sealed: list[dict] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    other: list[dict] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)
    listed: bool = False      # the text states contents at all

    @property
    def complete(self) -> bool:
        return self.listed and not self.unresolved and self.category not in PACKS


def expansion_of(group_name: str) -> str:
    """'SV08: Surging Sparks' -> 'surging sparks'; 'SM - Crimson Invasion' -> 'crimson invasion';
    'SWSH01: Sword & Shield Base Set' -> 'sword shield' (packs say 'Sword & Shield booster packs')."""
    name = re.split(r":\s+|\s+-\s+", group_name, maxsplit=1)[-1]
    return re.sub(r"\s+base set$", "", fold(name))


# --- promo cards ------------------------------------------------------------------------------------------------


@dataclass
class PromoListing:
    product_id: int
    group: Group
    pokemon: str          # folded name without number or edition
    stamps: frozenset[str]  # Pokémon Center, Staff or other stamp named in the listing
    released: dt.date | None
    number: str


# Stamps a listing can carry. "Exclusive" is not one: TCGplayer writes "(Surging Sparks ETB Exclusive)" on plain
# promos too.
STAMP_WORDS = ("pokemon center", "staff", "prerelease", "league", "winner", "championship", "pre release",
               # Foil patterns a listing names; a line must name the same one.
               "cosmos", "reverse", "etched", "cracked ice", "galaxy")


def stamps_in(text: str) -> frozenset[str]:
    folded = fold(text)
    return frozenset(w.replace("pre release", "prerelease") for w in STAMP_WORDS if w in folded)


def promo_listing(product: dict, group: Group) -> PromoListing | None:
    ext = {e.get("name"): e.get("value") for e in product.get("extendedData") or []}
    if not ext.get("Number"):
        return None
    name = product.get("name", "")
    base = re.split(r"\s+-\s+|\s+\(", name, maxsplit=1)[0]
    # The group's publish date is the promo series' start, years before most of its cards: never use it.
    released = release_date(product)
    return PromoListing(
        product_id=product["productId"], group=group, pokemon=fold(base),
        stamps=stamps_in(name), number=str(ext["Number"]),
        released=dt.date.fromisoformat(released) if released else None,
    )


class PromoResolver:
    """Pins 'N foil promo card featuring X' to a TCGdex card and variant through TCGplayer's promo listings."""

    def __init__(self, fetcher: Fetcher, promo_groups: list[Group]):
        self.fetcher = fetcher
        self.by_name: dict[str, list[PromoListing]] = defaultdict(list)
        for group in promo_groups:
            for product in group.products:
                listing = promo_listing(product, group)
                if listing:
                    self.by_name[listing.pokemon].append(listing)

    def candidates(self, pokemon: str, stamps: frozenset[str], released: str | None, serie: str | None) -> list[PromoListing]:
        """Same Pokémon and stamp, in the product's serie's promo set. TCGplayer gives most promo singles no
        release date; a dated listing far from the product's release is dropped."""
        found = [p for p in self.by_name.get(fold(pokemon), [])
                 if p.stamps == stamps and (serie is None or p.group.serie == serie)]
        if released:
            day = dt.date.fromisoformat(released)
            found = [p for p in found if not p.released or abs((p.released - day).days) <= PROMO_WINDOW_DAYS]
        return found

    def tcgdex_card(self, listing: PromoListing) -> dict | None:
        """The TCGdex card item for a TCGplayer promo listing, or None when TCGdex has no variant for it."""
        tcgdex_set = self.fetcher.get(f"{TCGDEX_API}/en/sets/{listing.group.set_id}")
        if not tcgdex_set:
            return None
        number = fold(listing.number).replace(" ", "")
        for brief in tcgdex_set.get("cards") or []:
            local = fold(str(brief.get("localId", ""))).replace(" ", "")
            if local.lstrip("0") != number.lstrip("0") and local != number:
                continue
            card = self.fetcher.get(f"{TCGDEX_API}/en/cards/{brief['id']}")
            for variant in (card or {}).get("variants_detailed") or []:
                third = variant.get("thirdParty") or {}
                if third.get("tcgplayer") == listing.product_id and variant.get("variantId"):
                    # TCGplayer names the stamped listing and TCGdex links it; when they disagree on the stamp,
                    # neither is trusted.
                    if ("pokemon center" in listing.stamps) != ("pokemon-center" in (variant.get("stamp") or [])):
                        return None
                    item = {"tcgdexCardId": card["id"], "tcgdexVariantId": variant["variantId"],
                            "tcgplayerProductId": listing.product_id}
                    if third.get("cardmarket") is not None:
                        item["cardmarketProductId"] = third["cardmarket"]
                    return item
        return None


# --- parsing contents -------------------------------------------------------------------------------------------

# "36 Packs" in a box counts packs too; a "3 Pack Blister" is a product, not packs.
PACK_RE = re.compile(COUNT + r"\s+(?:sealed\s+)?(?:(?P<what>[^.;|]*?)\s+)?(?:booster\s+)?packs?\b(?!\s*-?\s*blister)"
                     r"(?P<rest>[^.;|]*)", re.I)
PROMO_RE = re.compile(COUNT + r"\s+(?P<kind>[^.;|]*?)\b(?:(?:promo(?:tional)?\s+)?(?:cards?|holofoil|holo)|"
                      r"promo(?:tional)?)\s+(?:featuring|of)\s+(?P<who>.+)$", re.I)
# "a promotional foil Meltan"
PROMO_NAMED_RE = re.compile(COUNT + r"\s+promo(?:tional)?\s+(?:foil|holofoil|holo)\s+(?:card\s+)?(?P<who>.+)$", re.I)
SET_FEATURE_RE = re.compile(r"\b(?:over \d+ (?:new )?cards|\d+ (?:new )?cards in the set|illustration rare|hyper rare|"
                            r"secret rare|ultra rare|ace spec|shiny vault|radiant pok)", re.I)
# An item that is cards we cannot name: the product is not complete.
UNNAMED_CARDS_RE = re.compile(r"\b(?:\d+-card|card)\s+(?:ready-to-play\s+|preconstructed\s+|pre-constructed\s+)?decks?\b|"
                              r"\bevolution line\b|\b(?:holo|holofoil|foil|rare|full art)\b.*\bcards?\b", re.I)
# A card mechanic named in an item ("2 powerful Pokémon ... Dragonite EX and Pidgeot EX"): cards. Case matters.
MECHANIC_RE = re.compile(r"\b(?:EX|GX|V|VMAX|VSTAR|V-UNION|BREAK|LV\.X)\b|\bex\b")
ACCESSORY_RE = re.compile(r"\b(?:sleeves?|markers?|coins?|pins?|box|binder|playmat|mat|dice|die|oversize|jumbo|"
                          r"stickers?|poster|figure|tin|art card|dangler|portfolio|magnet|counters?|guide|rulebook|"
                          r"booklet|dividers?)\b", re.I)
# "3 Cards", "11 randomly inserted game cards": cards, unless they are Energy, code, art, rules or reference cards.
PLAIN_CARDS_RE = re.compile(r"^\s*\S+\s+(?!.*\b(?:energy|code|art|reference|rules?|checklist|tip|strategy|guide)\b)"
                            r"(?:[\w-]+\s+){0,3}cards?\b", re.I)
EACH_PACK_RE = re.compile(r"\beach\s+(?:\w+\s+){0,4}?(?:booster\s+)?pack\s+(?:contains|includes|has)\b", re.I)
LEAD_RE = re.compile(r"^" + COUNT + r"\b\s*", re.I)
# "Each blister comes with 3 X booster packs and a promotional card of Y."
LIST_SENTENCE_RE = re.compile(r"\b(?:comes with|contains|includes|including|containing|you'll find)\s+(?P<items>.+)$",
                              re.I)
LIST_HEADER_RE = re.compile(r"\b(?:includes|contains|contents|you'll find|inside)\s*:?\s*$", re.I)
ITEM_SPLIT_RE = re.compile(r"[,;]\s*(?:and\s+|plus\s+)?|\s+(?:and|plus)\s+(?=(?:" + COUNT[1:] + r"\b)", re.I)


def list_items(text: str) -> list[str]:
    """The counted items of a prose list. A segment without a leading count belongs to the item before it, so
    'featuring Sylveon, Leafeon, or Glaceon' and 'box to hold everything, with 4 dividers' stay whole. A clause
    about the packs inside ('packs, each containing 10 cards and 1 basic Energy') is cut."""
    text = re.sub(r"[“”\"]", "", cut_each_pack(text))
    items: list[str] = []
    for segment in ITEM_SPLIT_RE.split(text):
        segment = segment.strip(" .!")
        if not segment:
            continue
        if LEAD_RE.match(segment) or not items:
            items.append(segment)
        elif len(segment.split()) <= 3 and ACCESSORY_RE.search(segment):
            items.append(f"1 {segment}")   # "1 TCGO Code, Coin": the coin is its own item
        else:
            items[-1] = f"{items[-1]}, {segment}"
    return [i for i in items if LEAD_RE.match(i)]


# A clause about the packs inside: "(each pack contains 11 randomly inserted game cards)", ", each containing ...".
EACH_CLAUSE_RE = re.compile(r"[,(]?\s*\beach\s+(?:\w+\s+){0,4}?(?:booster\s+)?pack\s+(?:contains|includes|has|with)\b|"
                            r",?\s*\beach\s+(?:containing|with|including|contains)\b", re.I)


def cut_each_pack(text: str) -> str:
    return EACH_CLAUSE_RE.split(text, maxsplit=1)[0]


CASE_GENERIC_WORDS = {"case", "display", "booster", "boxes", "box", "pack", "packs", "ct", "count", "sealed"}


class Parser:
    def __init__(self, groups_by_expansion: dict[str, Group], child_of: dict[tuple[int, str], str],
                 families: dict[tuple[int, str], list[tuple[str, str]]], promos: PromoResolver):
        self.groups_by_expansion = groups_by_expansion
        self.child_of = child_of           # (group id, category) -> the group's plain product of that category
        self.families = families           # (group id, category) -> [(family id, folded name)]
        self.promos = promos

    def pack_family(self, phrase: str, draft: Draft) -> str | None:
        """The booster pack family a pack phrase names: an expansion it names, else the product's own set when the
        product is a single-set container (box, bundle, ETB, ...)."""
        folded = re.sub(r"\s+", " ", re.sub(r"\b(?:booster|sealed|additional)\b", " ", fold(phrase))).strip()
        if re.search(r"\brandom\b", folded):
            return None   # "1 random XY booster pack": any set of the series
        named = [(m.start(), m.end(), e, g) for e, g in self.groups_by_expansion.items()
                 if e and (m := re.search(rf"\b{re.escape(e)}\b", folded))]
        if re.search(r"\bor\b", folded) and len({n[3].group_id for n in named}) > 1:
            # "Black Bolt or White Flare booster packs, respectively": the product's own set, if it is one of them.
            own = [n for n in named if n[3].group_id == draft.group.group_id]
            return self.child_of.get((draft.group.group_id, "booster_pack")) if own else None
        # "Prismatic Evolutions" also contains "Evolutions": a match inside a longer one is not the expansion.
        named = [n for n in named
                 if not any(o[0] <= n[0] and n[1] <= o[1] and o[1] - o[0] > n[1] - n[0] for o in named)]
        # "Scarlet & Violet—Black Bolt" also names the Scarlet & Violet base set: a series name loses to a real one.
        real = [n for n in named if not re.fullmatch(SERIES_PREFIX[1:], n[2])]
        # Only a series named ("3 XY booster packs"): never that series' base set.
        series_only = bool(re.fullmatch(rf"(?:pokemon tcg |pokemon )?{SERIES_PREFIX[1:]}", folded)) or \
            (bool(named) and not real)
        if real and not series_only:
            group = max(real, key=lambda t: (t[1] - t[0], t[0]))[3]
            return self.child_of.get((group.group_id, "booster_pack"))
        generic = folded in ("", "pokemon tcg", "pokemon")
        own_set = ("booster_box", "half_booster_box", "booster_bundle", "case")
        # "3 XY booster packs" in a BREAKthrough blister names the series, not the XY base set.
        if (generic and draft.category in own_set) or (series_only and draft.category in (*own_set, "blister")):
            return self.child_of.get((draft.group.group_id, "booster_pack"))
        return None

    def parse(self, draft: Draft) -> None:
        parts = text_parts(card_text(draft.product))
        released = release_date(draft.product)
        if draft.category == "case":
            # A case's text is usually its inner product's: only a stated unit count describes the case.
            # "10 Elite Trainer Boxes. 5 of each variety": the mix is stated, not which unit is which.
            if re.search(r"\bof each\b|\bassorted\b|\bmixed\b", fold(" ".join(t for _, t in parts))):
                draft.listed = True
                draft.unresolved.append({"line": "case mix", "reason": "case mixes several products"})
                parts = []
            # The first sentence that counts the case's units is the case; later ones describe the units.
            for index, (_, text) in enumerate(parts):
                for sentence in sentences(text):
                    if not draft.listed and LIST_SENTENCE_RE.search(sentence) \
                            and self.parse_case(draft, sentence, f"line[{index}]"):
                        draft.listed = True
        else:
            for index, line in self.content_items(parts):
                draft.listed = True
                self.parse_line(draft, line, released, f"line[{index}]")
        text = fold(" ".join(t for _, t in parts))
        name = fold(draft.product["name"])
        if draft.category in ("booster_box", "half_booster_box") and not draft.sealed:
            # "There are 36 packs per display": the box's own packs, said without a list.
            if (per := re.search(rf"\b{COUNT}\s+(?:booster\s+)?packs?\s+(?:per|in each|in every|in a)\s+"
                                 r"(?:display|box)\b", text)):
                child = self.child_of.get((draft.group.group_id, "booster_pack"))
                draft.unresolved = [u for u in draft.unresolved if "pack" not in fold(u.get("line", ""))]
                draft.other = [o for o in draft.other if not re.search(r"\b(?:packs?|displays?)\b", fold(o["name"]))]
                self.add_sealed(draft, child, count_of(per.group(1)), per.group(0), "text")
                draft.listed = True
        if re.search(r"\bset of \d+\b|\b\d+ pack set\b", name):
            # A bundle of N whole products: one unit's text would undercount it, so nothing is listed.
            draft.sealed, draft.cards, draft.other = [], [], []
            draft.unresolved.append({"line": "set of products", "reason": "set of several products"})
        if draft.category in ("theme_deck", "battle_deck") or re.search(r"\bdecks?\b|\btrainer kit\b", name):
            draft.unresolved.append({"line": "deck list", "reason": "deck list not listed"})
        if text and ("pokemon center" in name) != ("pokemon center" in text):
            # TCGplayer sometimes gives the Pokémon Center edition the standard edition's text, or the reverse.
            draft.unresolved.append({"line": "product text", "reason": "text describes another edition"})
        if draft.category in PACKS:
            draft.unresolved.append({"line": "random cards", "reason": "booster pack cards are random"})

    @staticmethod
    def content_items(parts: list[tuple[bool, str]]) -> list[tuple[int, str]]:
        """Bullets when the text has any; else the counted lines under an 'includes:' header; else the items of
        sentences such as 'Each blister comes with 3 X booster packs and a promotional card of Y.'"""
        # Bullets come in blocks; a block that describes the expansion ("Over 160 cards", "22 illustration rare
        # Pokémon") is not the product's contents.
        # A short counted line next to a bullet ("A code card for Pokémon TCG Live" after the last bullet) belongs
        # to the list.
        listy = [bullet for bullet, _ in parts]
        for i, (bullet, text) in enumerate(parts):
            near = (i > 0 and parts[i - 1][0]) or (i + 1 < len(parts) and parts[i + 1][0])
            if not bullet and near and LEAD_RE.match(text) and len(text) < 120:
                listy[i] = True
        blocks: list[list[tuple[int, str]]] = []
        for i, (_, text) in enumerate(parts):
            if listy[i]:
                if blocks and blocks[-1][-1][0] == i - 1:
                    blocks[-1].append((i, text))
                else:
                    blocks.append([(i, text)])
        # A bullet holding two counted items ("2 coin condition markers, 1 coin") is split.
        bullets = [(i, item) for block in blocks if not any(SET_FEATURE_RE.search(t) for _, t in block)
                   for i, text in block if not EACH_PACK_RE.search(text) for item in (list_items(text) or [text])]
        if bullets:
            return bullets
        # Counted lines under an "includes:" header, up to the next long paragraph. Lines in between that are not
        # counted ("Each booster pack contains 10 cards", "Cards vary by pack.") are skipped, not an end.
        items, under_header = [], False
        for index, (_, text) in enumerate(parts):
            if LIST_HEADER_RE.search(text):
                under_header = True
            elif len(text) >= 160:
                under_header = False
            elif under_header and LEAD_RE.match(text) and not EACH_PACK_RE.search(text):
                items.append((index, text))
        if items:
            return items
        # "(Each pack contains 10 random cards)" describes the packs inside, not the product: cut it, keep the rest.
        return [(index, item) for index, (_, text) in enumerate(parts) for sentence in sentences(text)
                if (found := LIST_SENTENCE_RE.search(cut_each_pack(sentence)))
                for item in list_items(found.group("items"))]

    def parse_case(self, draft: Draft, sentence: str, where: str) -> bool:
        """The units a case holds, from a sentence such as 'contains 6 booster boxes of 36 booster packs'.
        True when the sentence gave a count."""
        folded = fold(sentence)
        if not re.search(r"\b(?:case|display)\b", folded):
            return False   # "Each tin contains two booster packs" describes the unit, not the case.
        if re.search(r"\bof each\b", folded):
            # "10 Elite Trainer Boxes, 5 of each variety": the mix is stated, not which unit is which.
            draft.unresolved.append({"line": sentence, "where": where, "reason": "case mixes several products"})
            return True
        sleeved = "sleeved" in fold(draft.product["name"])
        for words, category in CASE_UNITS:
            if (found := re.search(rf"\b{COUNT}\s+(?:\w+\s+)??(?:{words})\b", folded)):
                if category == "booster_pack" and sleeved:
                    category = "sleeved_booster_pack"
                child = self.case_child(draft, category)
                return self.add_sealed(draft, child, count_of(found.group(1)), sentence, where)
        return False

    def case_child(self, draft: Draft, category: str) -> str | None:
        """The unit a case holds, keeping the case's qualifier: an Enhanced Booster Case holds Enhanced Booster
        Boxes, a Pokémon Center ETB Case holds Pokémon Center ETBs."""
        name = re.sub(rf"\b{re.escape(draft.group.expansion)}\b", " ", fold(draft.product["name"]))
        qualifier = set(name.split()) - CASE_GENERIC_WORDS - set(category.split("_")) - {"elite", "trainer"}
        qualifier = {w for w in qualifier if not w.isdigit()}
        if not qualifier:
            return self.child_of.get((draft.group.group_id, category))
        fits = [(len(n.split()), fid) for fid, n in self.families.get((draft.group.group_id, category), [])
                if qualifier <= set(n.split())]
        return min(fits)[1] if fits else None

    def add_sealed(self, draft: Draft, child: str | None, count: int, line: str, where: str) -> bool:
        if child and child != draft.family_id:
            draft.sealed.append({"product": child, "count": count})
        else:
            draft.unresolved.append({"line": line, "where": where, "reason": "booster pack set not identified"})
        return True

    def parse_line(self, draft: Draft, line: str, released: str | None, where: str) -> None:
        if not LEAD_RE.match(line) and (found := LIST_SENTENCE_RE.search(line)):
            # A bullet that is a sentence: "Each Chaos Rising Booster Box contains 18 booster packs".
            for item in list_items(found.group("items")):
                self.parse_line(draft, item, released, where)
            return
        folded = fold(line)
        if (pack := PACK_RE.match(line)) and "code" not in folded:
            phrase = pack.group("what") or ""
            if not phrase and (after := re.search(r"\bfrom\s+(.+)$", pack.group("rest") or "", re.I)):
                phrase = after.group(1)
            child = self.pack_family(phrase, draft)
            self.add_sealed(draft, child, count_of(pack.group(1)), line, where)
            return
        unparenthesised = re.sub(r"[()]", " ", line)
        promo = PROMO_RE.match(unparenthesised) or PROMO_NAMED_RE.match(unparenthesised)
        if promo and not re.search(r"oversize|jumbo|metal|sleeve|pin\b|coin|playmat|binder", folded):
            self.add_promo(draft, line, count_of(promo.group(1)), promo.group("who"), released, where)
            return
        # Cards never go to `other` (it is for everything that is not a card): a card we cannot name is reported
        # and makes the product partial.
        if re.search(r"\bpromo(?:tional)?\b", folded) and "code card" not in folded:
            # "a promotional card", or a deck "including 1 of 4 unique foil promo cards".
            draft.unresolved.append({"line": line, "where": where, "reason": "promo set not pinned to one card"})
        elif re.search(r"\brandom\b", folded):
            draft.unresolved.append({"line": line, "where": where, "reason": "random cards"})
        elif (UNNAMED_CARDS_RE.search(line) or MECHANIC_RE.search(line) or PLAIN_CARDS_RE.search(line)) \
                and not ACCESSORY_RE.search(line):
            # An oversize card is a display piece no card dataset lists, so it stays an `other` item.
            draft.unresolved.append({"line": line, "where": where, "reason": "cards not named"})
        else:
            lead = LEAD_RE.match(line)
            count = count_of(lead.group(1)) if lead else 1
            # Keep the item, drop the marketing after it: "art card ... —you can collect and combine all 5!"
            name = re.split(r"\s*(?:—|!|\(suitable)", line[lead.end():] if lead else line)[0].strip(" ,.;:")
            if name:
                draft.other.append({"name": name[:1].upper() + name[1:], "count": count})

    def add_promo(self, draft: Draft, line: str, count: int, who: str, released: str | None, where: str) -> None:
        who = re.sub(r"\s+with\s+(?:a|the)\s+.*$", "", who).strip(" .")
        if count == 1 and re.search(r"\bor\b", who):
            # "featuring Sylveon, Leafeon, or Glaceon": one listing sells every version, and the product's own
            # name says which this is ("... [Sylveon]"); without that the card is not pinned.
            options = [o.strip() for o in re.split(r",\s*(?:or\s+)?|\s+or\s+", who) if o.strip()]
            named = [o for o in options if fold(o) and fold(o) in fold(draft.product["name"])]
            if len(named) != 1:
                draft.unresolved.append({"line": line, "where": where, "reason": "promo is one of several"})
                return
            who = named[0]
        if re.search(r"\b(each|one of|1 of|random|assorted|unique)\b", fold(line)) or count > 1:
            names = [n for n in re.split(r",\s*|\s+and\s+", who) if n.strip()]
            if count > 1 and len(names) == count:
                for name in names:
                    self.add_promo(draft, f"1 promo card featuring {name}", 1, name, released, where)
                return
            draft.unresolved.append({"line": line, "where": where, "reason": "promo set not pinned to one card"})
            return
        found = self.promos.candidates(who, stamps_in(line), released, draft.group.serie)
        if len(found) != 1:
            reason = "no promo listing" if not found else f"{len(found)} promo listings match"
            draft.unresolved.append({"line": line, "where": where, "reason": reason,
                                     "candidates": [p.product_id for p in found]})
            return
        card = self.promos.tcgdex_card(found[0])
        if card is None:
            draft.unresolved.append({"line": line, "where": where, "reason": "TCGdex has no variant for listing",
                                     "candidates": [found[0].product_id]})
            return
        draft.cards.append({**card, "count": 1, "role": "promo"})


# --- assembling families ----------------------------------------------------------------------------------------


def family_file(draft: Draft, cardmarket: dict[int, int]) -> dict:
    product = draft.product
    release = {"language": LANGUAGE, "name": product["name"]}
    if (day := release_date(product)):
        release["releaseDate"] = day
    release["identifiers"] = {"tcgplayerProductIds": [product["productId"]]}
    release["sources"] = [product["url"]]
    data = {"id": draft.family_id, "region": REGION, "set": draft.group.set_id, "category": draft.category,
            "name": product["name"]}
    if product["productId"] in cardmarket:
        data["identifiers"] = {"cardmarketProductId": cardmarket[product["productId"]]}
    data["contentsStatus"] = "complete" if draft.complete else "partial"
    contents = {k: v for k, v in (("sealed", draft.sealed), ("cards", draft.cards), ("other", draft.other)) if v}
    data["contents"] = contents
    notes = ["Generated from TCGplayer's product text."]
    if draft.category in PACKS:
        notes.append("Booster pack cards are random.")
    elif not draft.listed:
        notes.append("The text states no contents.")
    elif draft.unresolved:
        notes.append("Not resolved: " + "; ".join(u.get("line", "") for u in draft.unresolved) + ".")
    data["notes"] = " ".join(notes)
    data["releases"] = [release]
    return data


def is_generated(family: Family) -> bool:
    releases = family.data.get("releases") or []
    return len(releases) == 1 and len(releases[0].get("sources") or []) == 1 and \
        "tcgplayer.com/product/" in releases[0]["sources"][0] and \
        str(family.data.get("notes", "")).startswith("Generated from TCGplayer")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--cache", default=ROOT / ".cache", type=Path)
    parser.add_argument("--group", type=int, action="append", help="only these TCGplayer group ids")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    fetcher = Fetcher(args.cache)

    mapping = {m["groupId"]: m for m in json.loads((ROOT / "mappings" / "tcgplayer_groups.json").read_text())
               if m["region"] == REGION}
    cardmarket = {m["tcgplayerProductId"]: m["cardmarketProductId"]
                  for m in json.loads((ROOT / "mappings" / "cardmarket_sealed.json").read_text())}
    tcgdex_sets = {s["id"]: s for s in fetcher.get(f"{TCGDEX_API}/en/sets") or []}

    groups: list[Group] = []
    for g in _results(fetcher.get(f"{TCGCSV}/{CATEGORY}/groups")):
        if g["groupId"] in mapping:
            group = Group(g["groupId"], mapping[g["groupId"]]["set"], g["name"], expansion_of(g["name"]),
                          g.get("publishedOn"))
            group.serie = ((fetcher.get(f"{TCGDEX_API}/en/sets/{group.set_id}") or {}).get("serie") or {}).get("id")
            group.products = _results(fetcher.get(f"{TCGCSV}/{CATEGORY}/{g['groupId']}/products"))
            groups.append(group)
    promo_groups = [g for g in groups if "promo" in fold(tcgdex_sets.get(g.set_id, {}).get("name", g.name))]
    product_groups = [g for g in groups if g not in promo_groups]

    existing = load(args.data)
    by_tcgplayer: dict[int, Family] = {}
    for family in existing:
        for release in family.data.get("releases", []):
            for pid in (release.get("identifiers") or {}).get("tcgplayerProductIds", []):
                by_tcgplayer[pid] = family
    taken = {f.data["id"] for f in existing}

    # Family ids first, so nested products can point at each other.
    drafts: list[Draft] = []
    child_of: dict[tuple[int, str], str] = {}
    kinds: dict[tuple[int, str], list[str]] = defaultdict(list)
    names: dict[str, str] = {}
    for group in product_groups:
        for product in group.products:
            if not is_sealed(product):
                continue
            category = classify(product["name"])
            if (family := by_tcgplayer.get(product["productId"])):
                family_id = family.data["id"]
                curated = not is_generated(family)
            else:
                stem = re.sub(rf"\b{re.escape(group.expansion)}\b", "", fold(product["name"])).strip()
                # "XY BREAKthrough Booster Pack" leaves "xy booster pack": the series is already in the set id.
                stem = re.sub(SERIES_PREFIX, "", stem).strip() or stem or category
                family_id = f"{group.set_id.lower()}-{slug(stem)}"
                if family_id in taken:
                    family_id = f"{family_id}-{product['productId']}"
                taken.add(family_id)
                curated = False
            kinds[(group.group_id, category)].append(family_id)
            names[family_id] = fold(product["name"])
            if not curated and (not args.group or group.group_id in args.group):
                drafts.append(Draft(product, group, family_id, category))
    # The set's own pack or box is the one named "<expansion> booster pack|booster|booster box".
    canonical = {"booster_pack": ("booster pack", "booster"), "booster_box": ("booster box",)}
    for (group_id, category), ids in kinds.items():
        group = next(g for g in product_groups if g.group_id == group_id)
        plain = [i for i in ids if names[i] in {f"{group.expansion} {s}" for s in canonical.get(category, ())}]
        if len(plain) == 1 or len(ids) == 1:
            child_of[(group_id, category)] = (plain or ids)[0]

    resolver = PromoResolver(fetcher, promo_groups)
    by_expansion = {g.expansion: g for g in product_groups}
    families = {key: [(fid, names[fid]) for fid in ids] for key, ids in kinds.items()}
    content_parser = Parser(by_expansion, child_of, families, resolver)
    review = []
    for draft in drafts:
        content_parser.parse(draft)
        if draft.unresolved or not draft.listed:
            review.append({"family": draft.family_id, "tcgplayerProductId": draft.product["productId"],
                           "name": draft.product["name"], "listed": draft.listed, "unresolved": draft.unresolved})

    files = {d.family_id: (d, family_file(d, cardmarket)) for d in drafts}
    complete = sum(1 for _, f in files.values() if f["contentsStatus"] == "complete")
    print(f"{len(groups)} groups ({len(promo_groups)} promo), {len(files)} generated families, "
          f"{complete} complete, {len(review)} to review")
    if args.dry_run:
        return 0
    for family_id, (draft, data) in files.items():
        path = args.data / REGION / draft.group.set_id / f"{family_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_path = ROOT / "review" / f"tcgplayer-{CATEGORY}.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    errors = validate(load(args.data), args.data)
    if errors:
        print("\n".join(errors[:50]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
