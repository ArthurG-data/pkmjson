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
                                             "format": "date"}}},
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
    sets = _source("sets.schema.json")
    return {
        "AllProducts": _release("AllProducts", "pkmjson AllProducts: every product in every language", entry, defs,
                                r"^[a-z0-9.-]+:[a-z-]+$"),
        "AllSets": _release("AllSets", "pkmjson AllSets: every set's printed name and logo per language",
                            {"$ref": "#/$defs/set"}, sets["$defs"], sets["propertyNames"]["pattern"]),
    }
