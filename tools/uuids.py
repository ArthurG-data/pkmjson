"""A UUID for every series, set, card, printing, oracle, product family and product release. Each UUID is given
once and kept for good, and is the same however often the tools run.

    uv run python tools/uuids.py

A UUID belongs to what a record is, which is not always its id. data/uuids/<kind>.json maps every identity key
ever seen to its UUID, per kind:

| kind | record id | identity key | aliases (what keeps a UUID through a re-keying) |
|---|---|---|---|
| `series` | `<region>/<serie>` | its id | renames in mappings/tcgdex_renames.json |
| `sets` | `<region>/<set>` | its id | its TCGplayer groups, renames |
| `cards` | `<region>/<card id>` | its id | `set:<set UUID>/<number>`: a card keeps its UUID when its set is renamed |
| `printings` | `<region>/<printing id>` | `<card UUID>:<language>:<version key>` | `variant:<card UUID>:<language>:<TCGdex variant id>`: a printing keeps its UUID when mappings/promo_types.csv changes its version key |
| `oracles` | the fingerprint of its rules text | `fingerprint:<sha1>` | `card:<card UUID>` of each card it holds: an oracle keeps its UUID when TCGdex fixes a typo in its text |
| `products` | `<family id>` | `tcgplayer:<lowest TCGplayer product id>`, else `id:<family id>` | its id, its TCGplayer and Cardmarket products |
| `productReleases` | `<family id>:<language>` | `<family UUID>:<language>` | its id, its TCGplayer products |

An identity key seen for the first time gets `uuid5(NAMESPACE, "<kind>:<record id>")`. If that UUID is taken it
gets `"<kind>:<record id>#2"`, then `#3`, and so on. So a rebuild from nothing gives the same UUIDs.

A record that replaces one that left takes that record's UUID instead. `bridges` records which UUID each alias was
last on. A known identity key keeps its UUID. A record that leaves keeps its key, so it gets its UUID back if it
returns, and nothing else may take that UUID. `keys` only grows and never changes a value. That is the whole
promise, and `history_errors` checks it between two versions of the registry (validate.py --since, run in CI).
"""
from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pkmjson import (
    CARDS,
    MAPPINGS,
    ROOT,
    SEALED,
    SERIES,
    SETS,
    UUIDS,
    Family,
    load,
    printing_id,
    read_json,
    write_cards,
    write_family,
    write_json,
)

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/ArthurG-data/pkmjson")
KINDS = ("series", "sets", "cards", "printings", "oracles", "products", "productReleases")
# The registry before it was split per kind.
LEGACY_REGISTRY = ROOT / "data" / "uuids.json"
RENAMES = MAPPINGS / "tcgdex_renames.json"
# Kinds with hundreds of thousands of records keep no bridges in the registry: their aliases are read from the files
# as they were before the run instead. A record re-keyed from one run to the next keeps its UUID; one that left for
# a run and came back under another key does not.
TRANSIENT = {"cards", "printings", "oracles"}
# Kinds whose identity starts with another record's UUID, saved grouped by it to keep the file small.
NESTED = {"printings"}


class Conflict(Exception):
    """Two live records whose identity keys hold one UUID: a record came back while the one that took its UUID is
    still here. A person decides which is which."""


def empty() -> dict:
    return {k: {"keys": {}, "bridges": {}} for k in KINDS}


def _unpack(kind: str, part: dict) -> dict:
    """A kind's registry as saved, with its keys flat again."""
    if kind not in NESTED:
        return {"keys": dict(part.get("keys", {})), "bridges": dict(part.get("bridges", {}))}
    return {"keys": {f"{owner}:{rest}": u for owner, group in part.get("keys", {}).items() for rest, u in group.items()},
            "bridges": dict(part.get("bridges", {}))}


def _pack(kind: str, part: dict) -> dict:
    keys = dict(sorted(part["keys"].items()))
    if kind in NESTED:
        grouped: dict[str, dict[str, str]] = {}
        for key, u in keys.items():
            owner, _, rest = key.partition(":")
            grouped.setdefault(owner, {})[rest] = u
        keys = grouped
    return {"keys": keys, "bridges": {} if kind in TRANSIENT else dict(sorted(part["bridges"].items()))}


def load_registry(path: Path = UUIDS) -> dict:
    """The registry in data/uuids/, one file per kind. A registry still in one file (data/uuids.json) is read too."""
    registry = empty()
    if path == UUIDS and LEGACY_REGISTRY.exists() and not path.exists():
        registry.update(read_json(LEGACY_REGISTRY))
    for kind in KINDS:
        if (path / f"{kind}.json").exists():
            registry[kind] = _unpack(kind, read_json(path / f"{kind}.json"))
    return registry


def save_registry(registry: dict, path: Path = UUIDS) -> None:
    """One file per kind, keys sorted, so a run that changes nothing leaves the files as they were."""
    for kind in KINDS:
        write_json(path / f"{kind}.json", _pack(kind, registry[kind]), indent=0)


def first(kind: str, rid: str, used: set[str]) -> str:
    """The UUID of a record first seen: uuid5 of its kind and id, or of `<kind>:<id>#2` and on in the rare case
    that UUID is taken."""
    n = 1
    while True:
        u = str(uuid.uuid5(NAMESPACE, f"{kind}:{rid}" + (f"#{n}" if n > 1 else "")))
        if u not in used:
            return u
        n += 1


@dataclass
class Entry:
    """One live record of a kind: its identity key, the aliases it answers to, and where its UUID goes."""
    identity: str
    aliases: list[str]
    targets: list[tuple[dict, str, str]]   # (record, field the UUID goes in, field it goes after)


def assign_kind(registry: dict, kind: str, entries: dict[str, Entry],
                previous: dict[str, str] | None = None) -> dict[str, str]:
    """{record id: UUID} for the live entries of `kind`, recording new identity keys and the bridges in
    `registry`. `previous` holds the aliases of the records as they were before the run, for a TRANSIENT kind.
    Nothing is written into the registry unless every record gets a UUID."""
    keys, bridges = registry[kind]["keys"], {**(previous or {}), **registry[kind]["bridges"]}
    out: dict[str, str] = {}
    held: dict[str, str] = {}   # UUID -> the live record id holding it
    order = sorted(entries, key=lambda r: (entries[r].identity, r))
    for rid in order:
        u = keys.get(entries[rid].identity)
        if u is None:
            continue
        if u in held:
            raise Conflict(f"{kind} {rid} ({entries[rid].identity}) and {held[u]} both hold {u}: one of them came "
                           f"back after the other took its UUID, or they share an identity")
        out[rid], held[u] = u, rid
    used = set(keys.values()) | set(bridges.values())
    for rid in (r for r in order if r not in out):
        # A record that left, named by one of this record's aliases: the first alias that names a free UUID.
        u = next((h for a in entries[rid].aliases if (h := keys.get(a) or bridges.get(a)) and h not in held),
                 None) or first(kind, rid, used)
        out[rid], held[u] = u, rid
        used.add(u)
    for rid, entry in entries.items():
        keys.setdefault(entry.identity, out[rid])
        if kind not in TRANSIENT:
            for alias in entry.aliases:
                if alias != entry.identity:
                    registry[kind]["bridges"][alias] = out[rid]
    for rid, entry in entries.items():
        for record, name, after in entry.targets:
            stamp_field(record, name, after, out[rid])
    return out


def stamp_field(record: dict, name: str, after: str | None, value: str) -> None:
    """Put `name` right after the record's `after` field (first, with None), in place."""
    rest = {k: v for k, v in record.items() if k != name}
    record.clear()
    if after is None:
        record[name] = value
    for k, v in rest.items():
        record[k] = v
        if k == after:
            record[name] = value


# --- products -----------------------------------------------------------------------------------------------------


def _tcgplayer(release: dict) -> list[int]:
    return sorted((release.get("identifiers") or {}).get("tcgplayerProductIds", []))


def family_tcgplayer(family: dict) -> list[int]:
    return sorted({pid for r in family.get("releases", []) for pid in _tcgplayer(r)})


def product_entries(families: list[dict]) -> dict[str, Entry]:
    out = {}
    for f in families:
        products = family_tcgplayer(f)
        cardmarket = (f.get("identifiers") or {}).get("cardmarketProductId")
        out[f["id"]] = Entry(f"tcgplayer:{products[0]}" if products else f"id:{f['id']}",
                             [f"id:{f['id']}", *(f"tcgplayer:{p}" for p in products),
                              *([f"cardmarket:{cardmarket}"] if cardmarket else [])],
                             [(f, "uuid", "id")])
    return out


def release_entries(families: list[dict]) -> dict[str, Entry]:
    return {f"{f['id']}:{r['language']}": Entry(f"{f['uuid']}:{r['language']}",
                                                 [f"id:{f['id']}:{r['language']}",
                                                  *(f"tcgplayer:{p}" for p in _tcgplayer(r))],
                                                 [(r, "uuid", "language")])
            for f in families for r in f["releases"]}


def assign(families: Iterable[dict], registry: dict) -> None:
    """Stamp a UUID on every family and release, in place, and record them in `registry`."""
    families = list(families)
    assign_kind(registry, "products", product_entries(families))
    assign_kind(registry, "productReleases", release_entries(families))


# --- the card spine -----------------------------------------------------------------------------------------------


def renames(path: Path | None = None) -> dict[str, dict[str, list[str]]]:
    """{kind: {new key: [old keys]}} from mappings/tcgdex_renames.json ({kind: {old: new}}): what TCGdex renamed,
    so the renamed series or set keeps its UUID, and its cards with it."""
    path = path or RENAMES
    out: dict[str, dict[str, list[str]]] = {"series": {}, "sets": {}}
    for kind, pairs in (read_json(path) if path.exists() else {}).items():
        for old, new in pairs.items():
            out.setdefault(kind, {}).setdefault(new, []).append(old)
    return out


def card_view(card: dict, region: str, serie: str | None) -> dict:
    """What tcgdex.group_cards reads of a card: its fields, its tree, its serie and its languages."""
    return {**card, "region": region, "serie": serie,
            "languages": list(dict.fromkeys(lang for v in card["versions"] for lang in v["printings"]))}


def oracle_keys(cards: dict[str, dict], sets: dict) -> dict[tuple[str, str], str]:
    """{(region, card id): oracle fingerprint}, by tcgdex.group_cards."""
    import tcgdex  # tcgdex builds on pkmjson, as this module does
    views = [card_view(c, body["region"], (sets.get(f"{body['region']}/{body['set']}") or {}).get("serie"))
             for body in cards.values() for c in body["cards"]]
    return tcgdex.group_cards(views)[0]


def spine_entries(series: dict, sets: dict, cards: dict[str, dict]):
    """The entry builders of the spine's kinds, in the order their aliases need: each a function of the UUIDs the
    kinds before it were given."""
    moved = renames()

    def series_entries(_):
        return {k: Entry(k, moved.get("series", {}).get(k, []), [(s, "uuid", "serie")]) for k, s in series.items()}

    def set_entries(_):
        return {k: Entry(k, [*moved.get("sets", {}).get(k, []),
                             *(f"tcgplayer:{g}" for g in (s.get("identifiers") or {}).get("tcgplayerGroupIds", []))],
                         [(s, "uuid", "set")]) for k, s in sets.items()}

    def card_entries(_):
        out = {}
        for body in cards.values():
            set_uuid = sets[f"{body['region']}/{body['set']}"]["uuid"]
            for c in body["cards"]:
                out[f"{body['region']}/{c['id']}"] = Entry(f"{body['region']}/{c['id']}",
                                                           [f"set:{set_uuid}/{c['localId']}"], [(c, "uuid", "id")])
        return out

    def printing_entries(_):
        out = {}
        for body in cards.values():
            for c in body["cards"]:
                for version in c["versions"]:
                    for lang, own in version["printings"].items():
                        variants = {**version.get("identifiers", {}), **own.get("identifiers", {})}.get(
                            "tcgdexVariantIds") or {}
                        out[f"{body['region']}/{printing_id(c['id'], lang, version)}"] = Entry(
                            f"{c['uuid']}:{lang}:{version.get('key', '')}",
                            [f"variant:{c['uuid']}:{lang}:{v}" for v in sorted(set(variants.values()))],
                            [(own, "uuid", None)])
        return out

    def oracle_entries(_):
        fingerprints = oracle_keys(cards, sets)
        members: dict[str, list[dict]] = collections.defaultdict(list)
        for body in cards.values():
            for c in body["cards"]:
                members[fingerprints[body["region"], c["id"]]].append(c)
        return {fp: Entry(f"fingerprint:{fp}", sorted(f"card:{c['uuid']}" for c in group),
                          [(c, "oracleId", "uuid") for c in group]) for fp, group in members.items()}

    return [("series", series_entries), ("sets", set_entries), ("cards", card_entries),
            ("printings", printing_entries), ("oracles", oracle_entries)]


@dataclass
class Spine:
    """Everything that carries a UUID, as the files hold it."""
    families: list[Family] = field(default_factory=list)
    series: dict = field(default_factory=dict)
    sets: dict = field(default_factory=dict)
    cards: dict[str, dict] = field(default_factory=dict)   # "<region>/<set>" -> the file's body
    registry_path: Path = UUIDS
    sealed_path: Path = SEALED

    @classmethod
    def load(cls, sealed: Path = SEALED, series: Path = SERIES, sets: Path = SETS, cards: Path = CARDS,
             registry: Path = UUIDS) -> Spine:
        return cls(load(sealed), read_json(series) if series.exists() else {}, read_json(sets) if sets.exists() else {},
                   load_cards(cards), registry, sealed)

    def stamp(self, previous: Spine | None = None) -> None:
        """Stamp every record, in place, and save the registry. `previous` is the spine as the files held it before
        the run: its records' aliases bridge a re-keyed card, printing or oracle to its UUID."""
        registry = load_registry(self.registry_path)
        before = (previous or self).aliases()
        for kind, entries in spine_entries(self.series, self.sets, self.cards):
            assign_kind(registry, kind, entries(registry), before.get(kind))
        assign((f.data for f in self.families), registry)
        save_registry(registry, self.registry_path)

    def aliases(self) -> dict[str, dict[str, str]]:
        """{kind: {alias: the UUID its record holds}} of the TRANSIENT kinds, for records that already have one."""
        try:
            live = self.live()
        except KeyError:   # records without UUIDs yet: nothing to bridge from
            return {}
        return {kind: {a: u for e in live[kind].values() if (u := _uuid_of(e.targets[0])) for a in e.aliases}
                for kind in TRANSIENT}

    def live(self) -> dict[str, dict[str, Entry]]:
        """Each kind's live entries, from the UUIDs the records hold."""
        out = {}
        for kind, entries in spine_entries(self.series, self.sets, self.cards):
            out[kind] = entries(None)
        families = [f.data for f in self.families]
        out["products"] = product_entries(families)
        out["productReleases"] = release_entries([f for f in families if "uuid" in f])
        return out


def load_cards(path: Path = CARDS) -> dict[str, dict]:
    """{"<region>/<set>": file body} of data/cards/."""
    return {f"{p.parent.name}/{p.stem}": read_json(p) for p in sorted(path.glob("*/*.json"))}


def _uuid_of(target: tuple[dict, str, str]) -> str | None:
    record, name, _ = target
    return record.get(name)


def errors(spine: Spine, registry: dict) -> list[str]:
    """Every record whose UUID is missing or is not the one data/uuids/ gives its identity, and any UUID two
    records of a kind share."""
    found: list[str] = []
    try:
        live = spine.live()
    except KeyError as error:   # a record a later kind's identity needs has no UUID yet
        return [f"a record has no {error.args[0]}: run tools/uuids.py"]
    for kind, entries in live.items():
        keys = registry[kind]["keys"]
        held: collections.Counter = collections.Counter()
        for rid, entry in sorted(entries.items()):
            values = {_uuid_of(t) for t in entry.targets}
            if None in values:
                found.append(f"{kind} {rid} has no uuid: run tools/uuids.py")
                continue
            if len(values) > 1 or keys.get(entry.identity) not in values:
                found.append(f"{kind} {rid}: uuid {sorted(values)[0]} is not {keys.get(entry.identity)}, the one "
                             f"data/uuids/ gives {entry.identity}: run tools/uuids.py")
            held[next(iter(values))] += 1
        found += [f"{kind}: uuid {u} is on {n} records" for u, n in sorted(held.items()) if n > 1]
    return found


def history_errors(before: dict, after: dict) -> list[str]:
    """What breaks the promise between two versions of the registry: an identity key dropped or given another
    UUID."""
    found = []
    for kind in KINDS:
        now = after.get(kind, {}).get("keys", {})
        for key, u in sorted(before.get(kind, {}).get("keys", {}).items()):
            if key not in now:
                found.append(f"{kind} {key}: its uuid {u} was dropped from data/uuids/")
            elif now[key] != u:
                found.append(f"{kind} {key}: its uuid changed from {u} to {now[key]}")
    return found


def _show(ref: str, rel: str) -> dict | None:
    shown = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=ROOT, capture_output=True, text=True)
    return json.loads(shown.stdout) if shown.returncode == 0 else None


def registry_at(ref: str) -> dict:
    """The registry as it was at git ref `ref`, in either layout; an empty one if it did not exist yet."""
    registry = empty()
    if (whole := _show(ref, LEGACY_REGISTRY.relative_to(ROOT).as_posix())) is not None:
        registry.update(whole)
    for kind in KINDS:
        if (part := _show(ref, (UUIDS / f"{kind}.json").relative_to(ROOT).as_posix())) is not None:
            registry[kind] = _unpack(kind, part)
    return registry


# --- for the import tools -----------------------------------------------------------------------------------------


def stamp(families: Iterable[Family], path: Path = UUIDS) -> None:
    """Stamp the product families and releases a tool is about to write, and save the registry."""
    registry = load_registry(path)
    assign((f.data for f in families), registry)
    save_registry(registry, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)
    spine = Spine.load()
    before = json.dumps([spine.series, spine.sets, spine.cards, [f.data for f in spine.families]])
    try:
        spine.stamp()
    except Conflict as error:
        print(error, file=sys.stderr)
        return 1
    if json.dumps([spine.series, spine.sets, spine.cards, [f.data for f in spine.families]]) != before:
        write_json(SERIES, spine.series, indent=1)
        write_json(SETS, spine.sets, indent=1)
        for key, body in spine.cards.items():
            write_cards(CARDS / f"{key}.json", body)
        for family in spine.families:
            write_family(family)
    if LEGACY_REGISTRY.exists():
        LEGACY_REGISTRY.unlink()
    registry = load_registry()
    live = spine.live()
    print("uuids: " + ", ".join(
        f"{len(live[k])} {k} ({len(set(registry[k]['keys'].values()) - {_uuid_of(e.targets[0]) for e in live[k].values()})} retired)"
        for k in KINDS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
