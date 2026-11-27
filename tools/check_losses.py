"""Compare the data with a git ref and fail when it lost more than a few of anything. Exits 1 on a loss.

    uv run python tools/check_losses.py [--base HEAD] [--allow-loss]

The importers rebuild what they own from the sites they read. So a page a site served wrong can drop a set's
products, a language's releases or the contents a text listed, without an error, and every other check passes on
data that is only missing something. This one counts what the data holds and compares each count with the same
count at --base:
- the families of each set;
- the releases of each language, and those with a release date;
- the families whose contents are complete;
- the card items;
- the booster packs with a pool;
- the sets with a name or a logo per language.

A count that fell by more than MIN_LOSS and by more than LOSS_SHARE of itself is a loss. A gain is never one.

Run it after a pipeline run, before committing (the default base is HEAD). CI runs it on a pull request against
the branch it targets. When a loss is meant (TCGplayer delisted a product), --allow-loss prints it and exits 0, and
"[allow-loss]" in a pull request's title skips the CI check.
"""
from __future__ import annotations

import argparse
import collections
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from pkmjson import ROOT, Family, load, read_json

MIN_LOSS = 2
LOSS_SHARE = 0.05
DATA = ("sets/sets.json", "data")


def tally(families: list[Family], sets: dict) -> collections.Counter:
    """{what: how many} for everything a loss could hide in."""
    count = collections.Counter()
    for f in families:
        d = f.data
        count["families"] += 1
        count[f"families in {d['region']}/{d['set']}"] += 1
        count["families with complete contents"] += d["contentsStatus"] == "complete"
        count["booster packs with a pool"] += "pool" in d["contents"]
        count["card items"] += len(d["contents"].get("cards", []))
        for r in d["releases"]:
            count[f"{r['language']} releases"] += 1
            count[f"{r['language']} releases with a release date"] += "releaseDate" in r
            count[f"{r['language']} releases with their own contents"] += "contents" in r
    for s in sets.values():
        count["sets"] += 1
        for lang, value in s["languages"].items():
            count[f"{lang} set names"] += "name" in value
            count[f"{lang} set logos"] += "logo" in value
    return count


def losses(base: collections.Counter, now: collections.Counter) -> list[str]:
    """A message for each count that fell by more than MIN_LOSS and by more than LOSS_SHARE of itself."""
    out = []
    for what, was in sorted(base.items()):
        lost = was - now.get(what, 0)
        if lost > MIN_LOSS and lost > LOSS_SHARE * was:
            out.append(f"{what}: {was} -> {now.get(what, 0)} (lost {lost})")
    return out


def load_at(ref: str, into: Path) -> tuple[list[Family], dict]:
    """The families and sets as committed at ref, unpacked into the directory into."""
    present = subprocess.run(["git", "ls-tree", "--name-only", ref, "--", *DATA], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout.split()
    archive = into / "base.tar"
    subprocess.run(["git", "archive", "--output", str(archive), ref, "--", *present], cwd=ROOT, check=True)
    with tarfile.open(archive) as tar:
        tar.extractall(into, filter="data")
    sets = into / "sets" / "sets.json"
    return load(into / "data"), read_json(sets) if sets.exists() else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="HEAD", help="the git ref to compare with (default HEAD)")
    parser.add_argument("--allow-loss", action="store_true", help="print the losses but exit 0")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="pkmjson-base-") as tmp:
        base = tally(*load_at(args.base, Path(tmp)))
    now = tally(load(ROOT / "data"), read_json(ROOT / "sets" / "sets.json"))
    found = losses(base, now)
    for message in found:
        print(message)
    print(f"{len(found)} losses against {args.base}")
    return 1 if found and not args.allow_loss else 0


if __name__ == "__main__":
    sys.exit(main())
