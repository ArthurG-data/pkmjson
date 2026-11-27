"""Helpers the tests share."""
import json

import uuids
from pkmjson import load, write_cards, write_json


def write_families(tmp_path, *families):
    """Write each family where validate expects it, with the UUIDs tools/uuids.py would give it, and load them
    back. The registry is not written, so validate skips its UUID checks."""
    uuids.assign(families, uuids.empty())
    for f in families:
        path = tmp_path / f["region"] / f["set"] / f"{f['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(f), encoding="utf-8")
    return load(tmp_path)


def card(card_id, *, name="Pikachu", attack="Thunder Shock", effect="Flip a coin.", versions=None, **facts):
    """A card as data/cards holds it, without UUIDs: by default one plain version printed in English."""
    return {"id": card_id, "localId": card_id.rsplit("-", 1)[1], "category": "Pokemon", "name": {"en": name},
            "hp": 60, "types": ["Lightning"], "stage": "Basic", "dexId": [25],
            "attacks": [{"cost": ["Lightning"], "name": {"en": attack}, "effect": {"en": effect}, "damage": 10}],
            **facts,
            "versions": versions or [{"finishes": ["nonfoil"], "identifiers": {"tcgdexVariantIds": {"nonfoil": "v1"}},
                                      "printings": {"en": {}}}]}


def write_spine(root, cards=(), families=(), sets=None):
    """A spine in root (sets/, data/cards/, data/sealed/, data/uuids/) holding the cards of set zz1 and the
    families, stamped by uuids.py. The uuids.Spine is returned."""
    sets = sets or {"international/zz1": {"region": "international", "set": "zz1", "serie": "zz",
                                          "languages": {}}}
    series = {"international/zz": {"region": "international", "serie": "zz", "name": {"en": "Zz"}}}
    spine = uuids.Spine(families=[], series=series, sets=sets,
                        cards={"international/zz1": {"region": "international", "set": "zz1", "cards": list(cards)}},
                        registry_path=root / "data" / "uuids", sealed_path=root / "data" / "sealed")
    if families:
        spine.families = write_families(root / "data" / "sealed", *families)
    spine.stamp()
    write_json(root / "sets" / "sets.json", spine.sets, indent=1)
    write_json(root / "sets" / "series.json", spine.series, indent=1)
    for key, body in spine.cards.items():
        write_cards(root / "data" / "cards" / f"{key}.json", body)
    for f in spine.families:
        write_json(f.path, f.data)
    return spine
