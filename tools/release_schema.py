"""The JSON schemas of the release files, dist/All*.json, built from the schemas in schema/.

A release file is {"meta": {"version", "date"}, "data": {key: record}}. AllProducts' records are the families
flattened per language (pkmjson.flatten), and AllSets' are sets/sets.json as it is. Building these from schema/ keeps
the two from drifting apart. build.py checks each file against its schema and writes the schema beside the file, so
a reader can check a download.
"""
from __future__ import annotations

import copy

from pkmjson import ROOT, read_json

BASE = "https://github.com/ArthurG-data/pkmjson/schema/release"


def _source(name: str) -> dict:
    return read_json(ROOT / "schema" / name)


def _release(name: str, title: str, record: dict, defs: dict, keys: str) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{BASE}/{name}.schema.json",
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "required": ["meta", "data"],
        "properties": {
            "meta": {"type": "object", "additionalProperties": False, "required": ["version", "date"],
                     "properties": {"version": {"type": "string", "minLength": 1},
                                    "date": {"description": "The day the data last changed.", "type": "string",
                                             "format": "date"},
                                    "sources": {"description": "The snapshot of each source the data was built "
                                                               "from: the TCGdex cards-database commit.",
                                                "type": "object", "additionalProperties": {"type": "string"}}}},
            "data": {"type": "object", "propertyNames": {"pattern": keys}, "additionalProperties": record},
        },
        "$defs": defs,
    }


def schemas() -> dict[str, dict]:
    """{release file name: its schema}."""
    product = _source("product.schema.json")
    family, defs = product["properties"], copy.deepcopy(product["$defs"])
    release = defs["release"]["properties"]
    pool = copy.deepcopy(defs["poolSet"])
    pool["required"] = ["set", "region"]
    entry = {
        "description": "One product in one language.",
        "type": "object",
        "additionalProperties": False,
        "required": ["uuid", "familyUuid", "familyId", "language", "region", "set", "category", "name",
                     "releaseDate", "identifiers", "contentsStatus", "contents", "sources"],
        "properties": {
            "uuid": {**release["uuid"], "description": "The release's UUID: this product in this language."},
            "familyUuid": {**family["uuid"], "description": "The UUID of the family, the product in every language."},
            "familyId": family["id"],
            "language": release["language"],
            "region": family["region"],
            "set": family["set"],
            "category": family["category"],
            "name": release["name"],
            "releaseDate": {"anyOf": [release["releaseDate"], {"type": "null"}]},
            "identifiers": {"type": "object", "additionalProperties": False, "properties": {
                **family["identifiers"]["properties"], **release["identifiers"]["properties"]}},
            "contentsStatus": family["contentsStatus"],
            "contents": {"type": "object", "additionalProperties": False, "required": ["sealed", "cards", "other"],
                         "properties": {
                             "sealed": {"type": "array", "items": {
                                 "type": "object", "additionalProperties": False, "required": ["product", "count"],
                                 "properties": {"product": {"description": "The AllProducts key of the product "
                                                                           "inside, in the same language.",
                                                            "type": "string", "pattern": r"^[a-z0-9.-]+:[a-z-]+$"},
                                                "count": {"type": "integer", "minimum": 1}}}},
                             "cards": {"type": "array", "items": {"$ref": "#/$defs/cardItem"}},
                             "other": {"type": "array", "items": {"$ref": "#/$defs/otherItem"}},
                             "pool": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/releasePoolSet"}}}},
            "sources": release["sources"],
            "notes": family["notes"],
        },
    }
    defs["releasePoolSet"] = pool
    defs["cardItem"]["properties"]["printing"] = {**release["uuid"], "description": "The UUID of the printing the "
                                                  "card is, in the release's language (else the home language's)."}
    pool["properties"]["setUuid"] = family["uuid"] | {"description": "The set's UUID."}
    pool["required"] = ["set", "region", "setUuid"]
    sets = _source("sets.schema.json")
    set_record = copy.deepcopy(sets["$defs"]["set"])
    set_record["properties"]["serie"] = {"type": "object", "additionalProperties": False,
                                         "required": ["id", "uuid", "name"],
                                         "properties": {"id": {"type": "string"}, "uuid": family["uuid"],
                                                        "name": {"type": "object"}}}
    cards = _source("cards.schema.json")
    card_defs = cards["$defs"]
    card = copy.deepcopy(card_defs["card"])
    uuid = family["uuid"]
    card["properties"].pop("versions")
    card["properties"].pop("imageLanguages")
    card["properties"].update(region=family["region"], set=family["set"], setUuid=uuid,
                              printings={"description": "The AllPrintings keys of the card's printings.",
                                         "type": "array", "items": {"type": "string"}})
    card["required"] = ["uuid", "id", "region", "set", "setUuid", "oracleId", "localId", "category", "name",
                        "printings"]
    version = card_defs["version"]["properties"]
    printing = {
        "type": "object", "additionalProperties": False,
        "required": ["uuid", "id", "cardUuid", "oracleId", "card", "region", "set", "setUuid", "localId", "language",
                     "versionKey", "finishes"],
        "properties": {
            "uuid": uuid, "id": {"description": "<card id>~<language>[~<promo types>]", "type": "string"},
            "cardUuid": uuid, "oracleId": uuid, "card": {"description": "The AllCards key of the card.", "type": "string"},
            "region": family["region"], "set": family["set"], "setUuid": uuid, "localId": {"type": "string"},
            "language": {"type": "string"}, "versionKey": {"type": "string"},
            "promoTypes": version["promoTypes"], "oversized": version["oversized"], "finishes": version["finishes"],
            "identifiers": version["identifiers"], "image": {"type": "string", "format": "uri"},
        },
    }
    keys = {"region": "^(international|asia)/"}
    natural = {"type": "string", "pattern": "^(international|asia)/"}
    pair = {"type": "array", "prefixItems": [natural, uuid], "items": False, "minItems": 2}
    by_uuid = {"type": "object", "propertyNames": {"format": "uuid"}}
    uuids_doc = {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{BASE}/AllUuids.schema.json",
        "title": "pkmjson AllUuids: every UUID and the natural key of its record",
        "type": "object", "additionalProperties": False, "required": ["meta", "data"],
        "properties": {
            "meta": _release("AllUuids", "", {}, {}, "")["properties"]["meta"],
            "data": {"type": "object", "additionalProperties": False,
                     "required": ["series", "sets", "cards", "printings", "oracles", "productReleases"],
                     "properties": {
                         "series": {**by_uuid, "additionalProperties": natural},
                         "sets": {**by_uuid, "additionalProperties": natural},
                         "cards": {**by_uuid, "additionalProperties": pair},
                         "printings": {**by_uuid, "additionalProperties": {
                             "type": "array", "prefixItems": [natural, {"type": "string"}, {"type": "string"}],
                             "items": False, "minItems": 3}},
                         "oracles": {**by_uuid, "additionalProperties": {"type": "array", "minItems": 1,
                                                                          "items": natural}},
                         "productReleases": {**by_uuid, "additionalProperties": {
                             "type": "array", "prefixItems": [{"type": "string", "pattern": ":"}, uuid],
                             "items": False, "minItems": 2}}}},
        },
    }
    return {
        "AllUuids": uuids_doc,
        "AllCards": _release("AllCards", "pkmjson AllCards: every TCGdex card, with its oracle id", card, {},
                             keys["region"]),
        "AllPrintings": _release("AllPrintings", "pkmjson AllPrintings: every card in every language and version",
                                 printing, {}, keys["region"]),
        "AllProducts": _release("AllProducts", "pkmjson AllProducts: every product in every language", entry, defs,
                                r"^[a-z0-9.-]+:[a-z-]+$"),
        "AllSets": _release("AllSets", "pkmjson AllSets: every set, its series, its TCGdex facts and its printed "
                            "name and logo per language", set_record, sets["$defs"], sets["propertyNames"]["pattern"]),
    }
