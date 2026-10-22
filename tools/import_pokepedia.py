"""Add French releases from Poképédia's product pages (pages using the template Infobox Produit JCC).

Each page states the product's French name, its English name (`nomen`), its expansion, how many booster packs it
holds and its French release date. The English name finds the international family; the page becomes that family's
`fr` release and its source. When the French box holds other packs than the English one (Poképédia lists them
under "Contenu supplémentaire", e.g. 2 Plasma Storm and 1 Boundaries Crossed instead of 3 Plasma Storm), the release
carries its own contents. A page that matches no family, or whose pack count cannot be reconciled, goes to
review/pokepedia.json.

    uv run python tools/import_pokepedia.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

from import_tcgplayer import NUMBER_WORDS, TCGDEX_API, Fetcher, fold
from pkmjson import ROOT, load, validate

API = "https://www.pokepedia.fr/api.php"
PAGE = "https://www.pokepedia.fr/"
LANGUAGE = "fr"
REGION = "international"
MIN_SCORE = 0.75
MARGIN = 0.08
# Words that say nothing about which product it is, series names included: Poképédia writes "Scarlet & Violet
# Paldea Evolved Elite Trainer Box" where TCGplayer writes "Paldea Evolved Elite Trainer Box".
STOP = {"pokemon", "tcg", "the", "of", "and", "with", "a", "an", "trading", "card", "game", "exclusive",
        "scarlet", "violet", "sword", "shield", "sun", "moon", "xy", "black", "white", "series"}


FRENCH_SERIES_WORDS = {"ecarlate", "et", "violet", "epee", "bouclier", "soleil", "lune", "noir", "blanc", "xy",
                       "diamant", "perle", "platine", "hs", "heartgold", "soulsilver", "ex", "mega", "evolution",
                       "megaevolution", "pokemon", "nb", "sl", "eb", "ev"}


def api(fetcher: Fetcher, **params) -> dict:
    query = urllib.parse.urlencode({"format": "json", "formatversion": "2", **params})
    return fetcher.get(f"{API}?{query}") or {}


def product_titles(fetcher: Fetcher) -> list[str]:
    titles, extra = [], {}
    while True:
        body = api(fetcher, action="query", list="embeddedin", eititle="Modèle:Infobox Produit JCC",
                   einamespace="0", eilimit="500", **extra)
        titles += [p["title"] for p in body.get("query", {}).get("embeddedin", [])]
        if "continue" not in body:
            return titles
        extra = {"eicontinue": body["continue"]["eicontinue"]}


def wikitexts(fetcher: Fetcher, titles: list[str]) -> dict[str, str]:
    out = {}
    for start in range(0, len(titles), 50):
        body = api(fetcher, action="query", prop="revisions", rvprop="content", rvslots="main",
                   titles="|".join(titles[start:start + 50]))
        for page in body.get("query", {}).get("pages", []):
            revisions = page.get("revisions") or []
            if revisions:
                out[page["title"]] = revisions[0]["slots"]["main"]["content"]
    return out


# --- wikitext -----------------------------------------------------------------------------------------------------


def plain(value: str) -> str:
    """Wiki markup to text: [[a|b]] -> b, [[a]] -> a, {{#time:d F Y|2013-05-08}} -> 2013-05-08."""
    value = re.sub(r"\{\{#time:[^|}]*\|([^}]*)\}\}", r"\1", value)
    value = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", value)
    value = re.sub(r"\{\{[^}]*\}\}|<[^>]+>|'''?", "", value)
    return re.sub(r"\s+", " ", value).strip()


def infobox(text: str) -> dict[str, str]:
    match = re.search(r"\{\{Infobox Produit JCC(.*?)\n\}\}", text, re.S)
    if not match:
        return {}
    fields = {}
    for line in match.group(1).split("\n|"):
        key, _, value = line.strip(" |\n").partition("=")
        if key.strip():
            fields[key.strip().lower()] = plain(value)
    return fields


def section(text: str, title: str) -> str:
    match = re.search(rf"==\s*{re.escape(title)}\s*==(.*?)(?:\n==[^=]|\Z)", text, re.S)
    return match.group(1) if match else ""


def french_packs(text: str) -> list[tuple[str, int]]:
    """(expansion, count) per booster line of "Contenu supplémentaire": a line naming one expansion, or sub-lines
    "** [[Expansion]] (×2)"."""
    body = section(text, "Contenu supplémentaire")
    packs: list[tuple[str, int]] = []
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if not re.match(r"\*\s*\S", line) or not re.search(r"booster", line, re.I):
            continue
        subs = []
        for sub in lines[i + 1:]:
            if not sub.startswith("**"):
                break
            if (m := re.search(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\][^(\n]*\((?:×|x)\s*(\d+)\)", sub)):
                subs.append((m.group(1), int(m.group(2))))
        if subs:
            packs += subs
        elif (m := re.match(r"\*\s*(\d+)\s.*?extension\s+\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", line)):
            packs.append((m.group(2), int(m.group(1))))
    return packs


# --- matching -----------------------------------------------------------------------------------------------------


def tokens(name: str) -> set[str]:
    words = fold(name).split()
    return {str(NUMBER_WORDS.get(w, w)) for w in words if len(w) > 1} - STOP


def similarity(a: set[str], b: set[str]) -> float:
    """Dice coefficient."""
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


class Catalog:
    def __init__(self, families, french_sets: dict[str, str]):
        self.families = [f for f in families if f.data["region"] == REGION]
        self.by_id = {f.data["id"]: f for f in self.families}
        self.french_sets = sorted(((fold(name), sid) for sid, name in french_sets.items() if fold(name)),
                                  key=lambda t: -len(t[0]))
        self.names = {}
        for f in self.families:
            names = {f.data["name"]} | {r["name"] for r in f.data["releases"] if r["language"] == "en"}
            self.names[f.data["id"]] = [tokens(n) for n in names]

    def set_of(self, expansion: str) -> str | None:
        """The set a French expansion name names. "Soleil et Lune Tonnerre Perdu" also contains the base set's
        name; a match counts only when nothing but series words is left over."""
        folded = re.sub(r"\bjcc\b", " ", fold(expansion))
        for name, sid in self.french_sets:
            if (m := re.search(rf"\b{re.escape(name)}\b", folded)):
                rest = set((folded[:m.start()] + " " + folded[m.end():]).split()) - FRENCH_SERIES_WORDS
                return sid if not rest else None
        return None

    def match(self, english_name: str, set_id: str | None):
        wanted = tokens(english_name)
        pool = [f for f in self.families if set_id is None or f.data["set"] == set_id]
        scored = sorted(((max(similarity(wanted, t) for t in self.names[f.data["id"]]), f) for f in pool),
                        key=lambda t: -t[0])
        if not scored or scored[0][0] < MIN_SCORE:
            return None, scored[0][0] if scored else 0.0
        if len(scored) > 1 and scored[1][0] > scored[0][0] - MARGIN:
            return None, scored[0][0]   # two families fit about as well: not trusted
        return scored[0][1], scored[0][0]

    def booster_family(self, set_id: str) -> str | None:
        packs = [f for f in self.families if f.data["set"] == set_id and f.data["category"] == "booster_pack"]
        plain_packs = [f for f in packs if re.search(r"-booster(?:-pack)?$", f.data["id"])]
        chosen = plain_packs if len(plain_packs) == 1 else packs
        return chosen[0].data["id"] if len(chosen) == 1 else None


def pack_count(contents: dict, catalog: Catalog) -> int:
    return sum(item["count"] for item in contents.get("sealed", [])
               if catalog.by_id.get(item["product"]) and
               catalog.by_id[item["product"]].data["category"] in ("booster_pack", "sleeved_booster_pack"))


# --- main ---------------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--cache", default=ROOT / ".cache", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    fetcher = Fetcher(args.cache, pause=0.5)

    french_sets = {s["id"]: s["name"] for s in fetcher.get(f"{TCGDEX_API}/fr/sets") or []}
    families = load(args.data)
    catalog = Catalog(families, french_sets)
    titles = product_titles(fetcher)
    texts = wikitexts(fetcher, titles)

    review, added, changed_paths = [], 0, set()
    for title in titles:
        text = texts.get(title, "")
        box = infobox(text)
        english = box.get("nomen")
        if not english:
            review.append({"page": title, "reason": "no English name"})
            continue
        set_id = catalog.set_of(box.get("extension", ""))
        family, score = catalog.match(english, set_id)
        if family is None:
            review.append({"page": title, "nomen": english, "set": set_id, "reason": "no family", "score": score})
            continue
        if any(r["language"] == LANGUAGE for r in family.data["releases"]):
            continue
        release = {"language": LANGUAGE, "name": box.get("nom") or title}
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", box.get("date-france", "")):
            release["releaseDate"] = box["date-france"]
        stated = int(box["nombre de boosters"]) if box.get("nombre de boosters", "").isdigit() else None
        ours = pack_count(family.data["contents"], catalog)
        packs = french_packs(text)
        french = [(catalog.set_of(e), n) for e, n in packs]
        if stated is not None and ours and stated != ours or (packs and len({s for s, _ in french}) > 1):
            # The French box holds other packs: give the release its own pack list, or skip it.
            sealed = [{"product": catalog.booster_family(s), "count": n} for s, n in french if s]
            if not packs or any(not item["product"] for item in sealed) or \
                    (stated is not None and sum(i["count"] for i in sealed) != stated):
                review.append({"page": title, "family": family.data["id"], "reason": "French packs differ",
                               "stated": stated, "ours": ours, "french": packs})
                continue
            others = [i for i in family.data["contents"].get("sealed", [])
                      if catalog.by_id.get(i["product"]) and catalog.by_id[i["product"]].data["category"]
                      not in ("booster_pack", "sleeved_booster_pack")]
            release["contents"] = {**family.data["contents"], "sealed": sealed + others}
        release["sources"] = [PAGE + urllib.parse.quote(title.replace(" ", "_"))]
        family.data["releases"].append(release)
        changed_paths.add(family.path)
        added += 1

    # A French release holds French nested products: give each booster pack it needs a French release too.
    for family in catalog.families:
        for release in [r for r in family.data["releases"] if r["language"] == LANGUAGE]:
            for item in release.get("contents", family.data["contents"]).get("sealed", []):
                child = catalog.by_id.get(item["product"])
                if child is None or any(r["language"] == LANGUAGE for r in child.data["releases"]):
                    continue
                if child.data["category"] == "booster_pack" and child.data["set"] in french_sets:
                    child.data["releases"].append({
                        "language": LANGUAGE, "name": f"Booster {french_sets[child.data['set']]}",
                        "sources": [release["sources"][0]]})
                    changed_paths.add(child.path)
    # A French release whose nested products still have no French release cannot stand.
    for family in catalog.families:
        kept = []
        for release in family.data["releases"]:
            children = [catalog.by_id.get(i["product"])
                        for i in release.get("contents", family.data["contents"]).get("sealed", [])]
            if release["language"] == LANGUAGE and any(
                    c is None or not any(r["language"] == LANGUAGE for r in c.data["releases"]) for c in children):
                review.append({"page": release["sources"][0], "family": family.data["id"],
                               "reason": "a nested product has no French release"})
                changed_paths.add(family.path)
                added -= 1
                continue
            kept.append(release)
        family.data["releases"] = kept

    print(f"{len(titles)} Poképédia pages, {added} French releases added, {len(review)} to review")
    if args.dry_run:
        return 0
    for family in catalog.families:
        if family.path in changed_paths:
            family.path.write_text(json.dumps(family.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_path = ROOT / "review" / "pokepedia.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    errors = validate(load(args.data), args.data)
    if errors:
        print("\n".join(errors[:50]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
