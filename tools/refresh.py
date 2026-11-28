"""Rebuild the whole dataset: every importer in the order each needs, then the UUIDs and the validator.

    uv run python tools/refresh.py [--refresh] [--online]

The importers share data/ and sets/, so the order matters:
0. import_tcgdex writes the card spine from the TCGdex dump tools/sync_tcgdex.sh made (.cache/tcgdex/), and every
   set's TCGdex facts into sets/sets.json.
1. import_tcgplayer writes the English families, then the Japanese ones (--category 85).
2. import_pokemon_card_jp names the Japanese releases.
3. import_pokepedia adds French releases, naming their booster packs from sets/sets.json.
4. import_sets writes sets/sets.json from the names those releases hold, and names each set's booster pack.
5. import_pools gives the booster packs their pools.
6. uuids stamps anything left without a UUID.
7. validate checks the result.

Running one importer alone leaves the data half rebuilt; this runs them all. --refresh fetches every source again
instead of reading .cache/. It stops at the first step that fails.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
IMPORTERS = (("import_tcgdex",), ("import_tcgplayer",), ("import_tcgplayer", "--category", "85"), ("import_pokemon_card_jp",),
             ("import_pokepedia",), ("import_sets",), ("import_pools",))


def commands(refresh: bool, online: bool) -> list[list[str]]:
    flag = ["--refresh"] if refresh else []
    # import_tcgdex reads the dump, not the web: tools/sync_tcgdex.sh refreshes it.
    steps = [[sys.executable, str(TOOLS / f"{tool}.py"), *rest, *(flag if tool != "import_tcgdex" else [])]
             for tool, *rest in IMPORTERS]
    return steps + [[sys.executable, str(TOOLS / "uuids.py")],
                    [sys.executable, str(TOOLS / "validate.py"), *(["--online"] if online else [])]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="fetch every source again instead of reading .cache/")
    parser.add_argument("--online", action="store_true", help="validate against the live sources at the end")
    args = parser.parse_args(argv)
    for command in commands(args.refresh, args.online):
        print(f"== {' '.join([Path(command[1]).stem, *command[2:]])}", flush=True)
        done = subprocess.run(command, cwd=TOOLS.parent)
        if done.returncode != 0:
            print(f"{Path(command[1]).stem} failed (exit {done.returncode}); the steps after it did not run",
                  file=sys.stderr)
            return done.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
