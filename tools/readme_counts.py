"""Rewrite the README's count of the card spine from the data: its sets, series, cards, oracles and printings.

The daily refresh changes the data, and the README states what it holds. CI checks that the sentence is the data's
(tests/test_pkmjson.py), so the refresh's pull request rewrites it with this tool.

    uv run python tools/readme_counts.py
"""
from __future__ import annotations

import collections
import re

from pkmjson import ROOT, printings
from uuids import Spine

README = ROOT / "README.md"
# The sentence, as it wraps in the README.
SENTENCE = re.compile(r"The data holds \d+ sets in \d+ series, and \d+ cards: \d+ international and \d+ Asian\. They "
                      r"are \d+ oracles\s+and \d+ printings\. \d+ printings carry a TCGplayer product and \d+ a "
                      r"Cardmarket product\.")


def spine_sentence(spine: Spine) -> str:
    cards = [(b["region"], c) for b in spine.cards.values() for c in b["cards"]]
    flat = [p for _, c in cards for p in printings(c)]
    regions = collections.Counter(region for region, _ in cards)

    def carrying(kind: str) -> int:
        return sum(bool((p.get("identifiers") or {}).get(kind)) for p in flat)

    return (f"The data holds {len(spine.sets)} sets in {len(spine.series)} series, and {len(cards)} cards: "
            f"{regions['international']} international and {regions['asia']} Asian. They are "
            f"{len({c['oracleId'] for _, c in cards})} oracles\nand {len(flat)} printings. "
            f"{carrying('tcgplayerProductIds')} printings carry a TCGplayer product and "
            f"{carrying('cardmarketProductIds')} a Cardmarket product.")


def rewrite(readme: str, spine: Spine) -> str:
    """The README with its spine sentence stating the data's counts."""
    text, found = SENTENCE.subn(lambda _: spine_sentence(spine), readme)
    if found != 1:
        raise SystemExit(f"README.md holds the spine's counts {found} times, not once")
    return text


def main() -> None:
    readme = README.read_text(encoding="utf-8")
    text = rewrite(readme, Spine.load())
    if text != readme:
        README.write_text(text, encoding="utf-8")
        print("README.md: the spine's counts rewritten")


if __name__ == "__main__":
    main()
