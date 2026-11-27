"""A UUID for every product family and every release of it. Each UUID is given once and kept for good, and is the
same however often the tools run.

    uv run python tools/uuids.py

A UUID belongs to what a record is, which is not always its id. A family's id is built from a TCGplayer product
name, and TCGplayer may rename the product. A family can also move to another set, or be renamed to keep the two
TCGdex trees apart (`sm10-booster-pack-576913` became `asia-sm10-booster-pack`). So each record has one identity
key, and data/uuids.json maps every identity key ever seen to its UUID, per kind:

- `products`, a family: `tcgplayer:<lowest TCGplayer product id of any release>`. A family TCGplayer does not sell
  uses `id:<family id>`.
- `productReleases`, a release: `<family UUID>:<language>`.

An identity key seen for the first time gets `uuid5(NAMESPACE, "<kind>:<record id>")`. If that UUID is taken it
gets `"<kind>:<record id>#2"`, then `#3`, and so on. So a rebuild from nothing gives the same UUIDs.

A record that replaces one that left takes that record's UUID instead. Its alias keys say what each key was last
on, in `bridges`. A family's aliases are its id, its TCGplayer products and its Cardmarket product. A release's
aliases are its id (`<family id>:<language>`) and its TCGplayer products. So a family that drops its TCGplayer
listing keeps its UUID through its id, and a family renamed with its listing kept keeps it through the listing.

A known identity key keeps its UUID. A record that leaves keeps its key in the registry, so it gets its UUID back
if it returns. The registry therefore lists retired records too: their keys stay, and nothing else may take their
UUIDs.

`keys` only grows and never changes a value. That is the whole promise, and `history_errors` checks it between two
versions of the registry (validate.py --since, run in CI).
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
import uuid
from collections.abc import Iterable
from pathlib import Path

from pkmjson import ROOT, Family, load, read_json, write_family, write_json

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/ArthurG-data/pkmjson")
REGISTRY = ROOT / "data" / "uuids.json"
KINDS = ("products", "productReleases")


class Conflict(Exception):
    """Two live records whose identity keys hold one UUID: a record came back while the one that took its UUID is
    still here. A person decides which is which."""


def empty() -> dict:
    return {k: {"keys": {}, "bridges": {}} for k in KINDS}


def load_registry(path: Path = REGISTRY) -> dict:
    registry = read_json(path) if path.exists() else empty()
    for kind in KINDS:
        registry.setdefault(kind, {"keys": {}, "bridges": {}})
    return registry


def save_registry(registry: dict, path: Path = REGISTRY) -> None:
    """Keys sorted, so a run that changes nothing leaves the file as it was."""
    write_json(path, {k: {part: dict(sorted(registry[k][part].items())) for part in ("keys", "bridges")}
                      for k in KINDS}, indent=1)


def first(kind: str, rid: str, used: set[str]) -> str:
    """The UUID of a record first seen: uuid5 of its kind and id, or of `<kind>:<id>#2` and on in the rare case
    that UUID is taken."""
    n = 1
    while True:
        u = str(uuid.uuid5(NAMESPACE, f"{kind}:{rid}" + (f"#{n}" if n > 1 else "")))
        if u not in used:
            return u
        n += 1


def _tcgplayer(release: dict) -> list[int]:
    return sorted((release.get("identifiers") or {}).get("tcgplayerProductIds", []))


def family_tcgplayer(family: dict) -> list[int]:
    return sorted({pid for r in family.get("releases", []) for pid in _tcgplayer(r)})


def identity(kind: str, record: dict) -> str:
    """The key a record's UUID belongs to: what the record is, which outlives its id."""
    if kind == "products":
        products = family_tcgplayer(record)
        return f"tcgplayer:{products[0]}" if products else f"id:{record['id']}"
    return f"{record['familyUuid']}:{record['language']}"


def _aliases(kind: str, record: dict) -> list[str]:
    """Every key the record answers to besides its identity."""
    if kind == "products":
        cardmarket = (record.get("identifiers") or {}).get("cardmarketProductId")
        return [f"id:{record['id']}", *(f"tcgplayer:{p}" for p in family_tcgplayer(record)),
                *([f"cardmarket:{cardmarket}"] if cardmarket else [])]
    return [f"id:{record['familyId']}:{record['language']}", *(f"tcgplayer:{p}" for p in _tcgplayer(record))]


def _assign(registry: dict, kind: str, records: dict[str, dict]) -> dict[str, str]:
    """{record id: UUID} for the live `records` of `kind`. Records new identity keys and the bridges in
    `registry`. Nothing is written into the registry unless every record gets a UUID."""
    keys, bridges = registry[kind]["keys"], registry[kind]["bridges"]
    ident = {rid: identity(kind, r) for rid, r in records.items()}
    out: dict[str, str] = {}
    held: dict[str, str] = {}   # UUID -> the live record id holding it
    for rid in sorted(records, key=lambda r: (ident[r], r)):
        u = keys.get(ident[rid])
        if u is None:
            continue
        if u in held:
            raise Conflict(f"{kind} {rid} ({ident[rid]}) and {held[u]} both hold {u}: one of them came back after "
                           f"the other took its UUID, or they share an identity")
        out[rid], held[u] = u, rid
    used = set(keys.values()) | set(bridges.values())
    for rid in sorted((r for r in records if r not in out), key=lambda r: (ident[r], r)):
        # A record that left, named by one of this record's aliases: the first alias that names a free UUID.
        u = next((h for a in _aliases(kind, records[rid]) if (h := keys.get(a) or bridges.get(a)) and h not in held),
                 None) or first(kind, rid, used)
        out[rid], held[u] = u, rid
        used.add(u)
    for rid, record in records.items():
        keys.setdefault(ident[rid], out[rid])
        for alias in _aliases(kind, record):
            if alias != ident[rid]:
                bridges[alias] = out[rid]
    return out


def _stamp(record: dict, after: str, u: str) -> None:
    """Put `uuid` right after the record's `after` field, in place."""
    rest = {k: v for k, v in record.items() if k != "uuid"}
    record.clear()
    for k, v in rest.items():
        record[k] = v
        if k == after:
            record["uuid"] = u


def _releases(families: Iterable[dict]) -> dict[str, dict]:
    """Each release with the family facts its identity and aliases need, keyed `<family id>:<language>`."""
    return {f"{f['id']}:{r['language']}": {**r, "familyId": f["id"], "familyUuid": f["uuid"]}
            for f in families for r in f["releases"]}


def assign(families: Iterable[dict], registry: dict) -> None:
    """Stamp a UUID on every family and release, in place, and record them in `registry`. The families go first:
    a release's identity is its family's UUID."""
    families = list(families)
    by_id = {f["id"]: f for f in families}
    for rid, u in _assign(registry, "products", by_id).items():
        _stamp(by_id[rid], "id", u)
    views = _releases(families)
    out = _assign(registry, "productReleases", views)
    for f in families:
        for r in f["releases"]:
            _stamp(r, "language", out[f"{f['id']}:{r['language']}"])


def stamp(families: Iterable[Family], path: Path = REGISTRY) -> None:
    """Load the registry, stamp every family and release, and save it: what each tool runs before it writes."""
    registry = load_registry(path)
    assign((f.data for f in families), registry)
    save_registry(registry, path)


def _live(families: Iterable[dict]) -> dict[str, dict[str, dict]]:
    families = [f for f in families if "uuid" in f]
    return {"products": {f["id"]: f for f in families}, "productReleases": _releases(families)}


def errors(families: Iterable[dict], registry: dict) -> list[str]:
    """The records whose UUID is missing or is not the one data/uuids.json gives their identity, and any UUID two
    records share."""
    families = list(families)
    found = [f"product {f['id']} has no uuid: run tools/uuids.py" for f in families if "uuid" not in f]
    every: collections.Counter = collections.Counter()
    for kind, records in _live(families).items():
        keys = registry[kind]["keys"]
        for rid, record in sorted(records.items()):
            if "uuid" not in record:
                found.append(f"{kind} {rid} has no uuid: run tools/uuids.py")
                continue
            key = identity(kind, record)
            if keys.get(key) != record["uuid"]:
                found.append(f"{kind} {rid}: uuid {record['uuid']} is not {keys.get(key)}, the one "
                             f"data/uuids.json gives {key}: run tools/uuids.py")
            every[record["uuid"]] += 1
    found += [f"uuid {u} is on {n} records" for u, n in sorted(every.items()) if n > 1]
    return found


def history_errors(before: dict, after: dict) -> list[str]:
    """What breaks the promise between two versions of the registry: an identity key dropped or given another
    UUID."""
    found = []
    for kind in KINDS:
        now = after.get(kind, {}).get("keys", {})
        for key, u in sorted(before.get(kind, {}).get("keys", {}).items()):
            if key not in now:
                found.append(f"{kind} {key}: its uuid {u} was dropped from data/uuids.json")
            elif now[key] != u:
                found.append(f"{kind} {key}: its uuid changed from {u} to {now[key]}")
    return found


def registry_at(ref: str, path: Path = REGISTRY) -> dict:
    """The registry as it was at git ref `ref`; an empty one if it did not exist yet."""
    rel = path.resolve().relative_to(ROOT)
    shown = subprocess.run(["git", "show", f"{ref}:{rel.as_posix()}"], cwd=ROOT, capture_output=True, text=True)
    return json.loads(shown.stdout) if shown.returncode == 0 else empty()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=ROOT / "data", type=Path)
    parser.add_argument("--registry", default=REGISTRY, type=Path)
    args = parser.parse_args(argv)
    families = load(args.data)
    before = {f.path: json.dumps(f.data) for f in families}
    try:
        stamp(families, args.registry)
    except Conflict as error:
        print(error, file=sys.stderr)
        return 1
    changed = [f for f in families if json.dumps(f.data) != before[f.path]]
    for family in changed:
        write_family(family)
    live = _live(f.data for f in families)
    registry = load_registry(args.registry)
    retired = {k: len(set(registry[k]["keys"].values()) - {r["uuid"] for r in live[k].values()}) for k in KINDS}
    print("uuids: " + ", ".join(f"{len(live[k])} {k} ({retired[k]} retired)" for k in KINDS) +
          f", {len(changed)} files stamped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
