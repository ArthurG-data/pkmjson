"""The card spine: TCGdex's variants as versions and printings, oracles across reprints, UUIDs that survive
re-keying, and the links products make to it."""
import copy
import json
from collections import Counter

import pytest

import import_tcgdex
import spine as spine_module
import tcgdex
import uuids
from conftest import card, write_spine
from pkmjson import Family, dumps_cards, printings

PROMOS = {("stamp", "pokemon-center"): ("pokemon-center", "stamp"), ("stamp", "1st-edition"): ("1st-edition", "edition")}


def _dump_card(variants, languages=("en", "fr"), **facts):
    return {"id": "zz1-1", "localId": "1", "set": "zz1", "serie": "zz", "region": "international",
            "category": "Pokemon", "name": {lang: "Pikachu" for lang in languages}, "languages": list(languages),
            "variants": variants, "thirdParty": facts.pop("thirdParty", {}), **facts}


# --- versions and printings -------------------------------------------------------------------------------------


def test_a_stamp_is_a_version_and_the_finish_types_are_three():
    found = tcgdex.versions(_dump_card([
        {"type": "normal", "variantId": "a"}, {"type": "reverse", "variantId": "b"},
        {"type": "holo", "stamp": ["pokemon-center"], "variantId": "c"}, {"type": "metal", "variantId": "d"}]),
        "en", PROMOS)
    assert set(found) == {"", "pokemon-center", "metal"}
    assert set(found[""]["finishes"]) == {"nonfoil", "reverse-holo"}
    assert set(found["pokemon-center"]["finishes"]) == {"holo"}
    assert found["metal"]["promos"] == {("metal", "uncategorized")} and set(found["metal"]["finishes"]) == {"holo"}


def test_a_stamp_its_whole_set_carries_is_a_promo_type_but_not_the_key():
    promos = {**PROMOS, ("stamp", "30th-anniversary"): ("30th-anniversary", "anniversary")}
    card_ = _dump_card([{"type": "holo", "stamp": ["30th-anniversary"], "variantId": "a", "thirdParty": {"tcgplayer": 7}},
                        {"type": "holo", "stamp": ["30th-anniversary", "pokemon-center"], "variantId": "b"}])
    found = tcgdex.versions(card_, "en", promos, set_stamp="30th-anniversary")
    assert set(found) == {"", "pokemon-center"}
    assert found[""]["promos"] == {("30th-anniversary", "anniversary")}
    assert tcgdex.marketplace_ids(card_, "international", "en", found[""])["tcgplayerProductIds"] == {"holo": 7}
    # Without the set's stamp, the same variants are two stamped versions.
    assert set(tcgdex.versions(card_, "en", promos)) == {"30th-anniversary", "30th-anniversary+pokemon-center"}


def test_a_card_whose_variants_differ_only_by_its_set_stamp_is_refused():
    promos = {("stamp", "mcdonalds"): ("mcdonalds", "retail")}
    card_ = _dump_card([{"type": "holo", "stamp": ["mcdonalds"], "variantId": "a"}, {"type": "normal", "variantId": "b"}])
    with pytest.raises(ValueError, match="zz1-1: a variant with and one without mcdonalds"):
        tcgdex.versions(card_, "en", promos, set_stamp="mcdonalds")


def test_the_set_stamps_name_sets_tcgdex_lists_and_known_promo_types():
    promos = {("stamp", "mcdonalds"): ("mcdonalds", "retail")}
    kept = {("international", "2012bw"): {}}
    assert import_tcgdex.set_stamp_errors({("international", "2012bw"): "mcdonalds"}, kept, promos) == []
    assert import_tcgdex.set_stamp_errors({("international", "zz9"): "mcdonalds",
                                           ("international", "2012bw"): "mcdonald"}, kept, promos) == [
        "mappings/set_stamps.json names international/zz9, which TCGdex does not list",
        "mappings/set_stamps.json gives international/2012bw mcdonald, which is no promo type of "
        "mappings/promo_types.csv"]


def test_the_set_stamps_mapping_loads_as_region_and_set():
    assert tcgdex.load_set_stamps()[("international", "30th")] == "30th-anniversary"


def test_a_variant_printed_in_some_languages_only_is_only_there():
    card_ = _dump_card([{"type": "normal", "variantId": "a"}, {"type": "reverse", "variantId": "b", "languages": ["fr"]}])
    assert set(tcgdex.versions(card_, "en", PROMOS)[""]["finishes"]) == {"nonfoil"}
    assert set(tcgdex.versions(card_, "fr", PROMOS)[""]["finishes"]) == {"nonfoil", "reverse-holo"}


def test_legacy_variants_are_rebuilt_as_the_compiler_does():
    card_ = _dump_card({"normal": False, "holo": True, "firstEdition": True}, legacyVariants=True)
    assert tcgdex.detailed_variants(card_) == [{"type": "holo", "variantId": "generated"},
                                               {"type": "holo", "stamp": ["1st-edition"], "variantId": "generated"}]
    assert tcgdex.detailed_variants(_dump_card(None, legacyVariants=True)) is None


def test_tcgplayer_ids_go_on_the_home_language_and_never_to_a_stamped_version():
    card_ = _dump_card([{"type": "normal", "variantId": "a"}], thirdParty={"tcgplayer": 7, "cardmarket": 8})
    plain = tcgdex.versions(card_, "en", PROMOS)[""]
    assert tcgdex.marketplace_ids(card_, "international", "en", plain) == {
        "tcgplayerProductIds": {"nonfoil": 7}, "cardmarketProductIds": {"nonfoil": 8}}
    assert tcgdex.marketplace_ids(card_, "international", "fr", plain) == {"cardmarketProductIds": {"nonfoil": 8}}
    stamped = {"promos": {("pokemon-center", "stamp")}, "oversized": False, "finishes": {"holo": {"variantId": "x"}}}
    assert tcgdex.marketplace_ids(card_, "international", "en", stamped) == {}
    unknown = {"promos": set(), "oversized": False, "finishes": {}}
    assert tcgdex.marketplace_ids(card_, "international", "en", unknown)["tcgplayerProductIds"] == {"unknown": 7}


def test_cardtrader_ids_go_on_every_language_of_the_version_that_names_them():
    dump = _dump_card([{"type": "normal", "variantId": "a", "thirdParty": {"cardtrader": 9}},
                       {"type": "holo", "stamp": ["pokemon-center"], "variantId": "c"}])
    plain, stamped = import_tcgdex.grouped_versions(dump, "international", tcgdex.load_promo_map(), Counter())
    assert plain["identifiers"] == {"tcgdexVariantIds": {"nonfoil": "a"}, "cardtraderIds": {"nonfoil": 9}}
    assert plain["printings"] == {"en": {}, "fr": {}}
    assert "cardtraderIds" not in stamped["identifiers"]


def test_versions_group_their_languages_and_lay_out_as_one_printing_each():
    dump = _dump_card([{"type": "normal", "variantId": "a", "thirdParty": {"tcgplayer": 7}},
                       {"type": "reverse", "variantId": "b", "languages": ["fr"]},
                       {"type": "holo", "stamp": ["pokemon-center"], "variantId": "c"}])
    versions = import_tcgdex.grouped_versions(dump, "international", tcgdex.load_promo_map(), Counter())
    plain = versions[0]
    assert "key" not in plain and plain["finishes"] == ["nonfoil"]
    assert plain["printings"]["fr"] == {"finishes": ["nonfoil", "reverse-holo"],
                                        "identifiers": {"tcgdexVariantIds": {"nonfoil": "a", "reverse-holo": "b"}}}
    assert plain["printings"]["en"] == {"identifiers": {"tcgplayerProductIds": {"nonfoil": 7}}}
    laid = {p["id"]: p for p in printings({"id": "zz1-1", "versions": versions})}
    assert set(laid) == {"zz1-1~en", "zz1-1~fr", "zz1-1~en~pokemon-center", "zz1-1~fr~pokemon-center"}
    assert laid["zz1-1~fr"]["finishes"] == ["nonfoil", "reverse-holo"]
    assert laid["zz1-1~en"]["identifiers"] == {"tcgdexVariantIds": {"nonfoil": "a"},
                                              "tcgplayerProductIds": {"nonfoil": 7}}
    assert laid["zz1-1~en~pokemon-center"]["versionKey"] == "pokemon-center"


def test_a_placeholder_set_file_does_not_replace_the_set_it_copies():
    kept, review = import_tcgdex.kept_sets([{"id": "BW3a", "file": "BW3b", "folder": "data-asia"},
                                            {"id": "BW3a", "file": "BW3a", "folder": "data-asia"}])
    assert kept[("asia", "BW3a")]["file"] == "BW3a" and review[0]["file"] == "BW3b"


def test_a_card_file_holds_one_card_per_line():
    body = {"region": "international", "set": "zz1", "cards": [card("zz1-1"), card("zz1-2")]}
    text = dumps_cards(body)
    assert json.loads(text) == body and len(text.splitlines()) == 4


# --- oracles ----------------------------------------------------------------------------------------------------


def _views(*cards_):
    return [uuids.card_view(c, "international", "zz") for c in cards_]


def _oracles(*cards_):
    keys, _ = tcgdex.group_cards(_views(*cards_))
    return [keys["international", c["id"]] for c in cards_]


def test_reprints_whose_wording_differs_share_an_oracle():
    one, two = _oracles(card("zz1-1", effect="Flip a coin. If heads, the Defending Pokémon is now Paralyzed."),
                        card("zz1-2", effect="Flip a coin. If heads, your opponent's Active Pokémon is now Paralyzed"))
    assert one == two


def test_a_field_tcgdex_left_empty_on_one_reprint_does_not_split_it():
    assert len(set(_oracles(card("zz1-1", retreat=1), card("zz1-2")))) == 1


def test_different_cards_of_one_name_and_a_pocket_card_stay_apart():
    a, b = _oracles(card("zz1-1"), card("zz1-2", attack="Quick Attack", effect="Draw a card."))
    assert a != b
    paper, pocket = card("zz1-1"), card("zz1-3")
    keys, _ = tcgdex.group_cards([uuids.card_view(paper, "international", "zz"),
                                  uuids.card_view(pocket, "international", "tcgp")])
    assert keys["international", "zz1-1"] != keys["international", "zz1-3"]


def test_a_japanese_pokemon_joins_the_english_oracle_with_its_numbers():
    english = card("zz1-1")
    japanese = {**card("ZZ1-1", name="ピカチュウ", attack="でんきショック", effect="コインを1回投げる。"),
                "name": {"ja": "ピカチュウ"}}
    for attack in japanese["attacks"]:
        attack["name"], attack["effect"] = {"ja": "でんきショック"}, {"ja": "コイン"}
    japanese["versions"] = [{"finishes": ["nonfoil"], "printings": {"ja": {}}}]
    keys, stats = tcgdex.group_cards([uuids.card_view(english, "international", "zz"),
                                      uuids.card_view(japanese, "asia", "ZZ")])
    assert keys["asia", "ZZ1-1"] == keys["international", "zz1-1"] and stats["linked"] == 1


# --- UUIDs --------------------------------------------------------------------------------------------------------


def test_the_spine_is_stamped_the_same_every_time(tmp_path):
    one = write_spine(tmp_path / "a", [card("zz1-1"), card("zz1-2")])
    two = write_spine(tmp_path / "b", [card("zz1-1"), card("zz1-2")])
    assert one.cards == two.cards and one.sets == two.sets
    again = copy.deepcopy(one.cards)
    one.stamp()
    assert one.cards == again
    c = one.cards["international/zz1"]["cards"][0]
    assert list(c)[:3] == ["id", "uuid", "oracleId"]
    assert c["oracleId"] == one.cards["international/zz1"]["cards"][1]["oracleId"]   # two prints, one card


def test_a_card_keeps_its_uuid_when_tcgdex_renames_its_set(tmp_path, monkeypatch):
    before = write_spine(tmp_path, [card("zz1-1")])
    old = before.cards["international/zz1"]["cards"][0]["uuid"]
    renames = tmp_path / "renames.json"
    renames.write_text(json.dumps({"sets": {"international/zz1": "international/zz2"}}))
    monkeypatch.setattr(uuids, "RENAMES", renames)
    after = uuids.Spine(series=before.series, registry_path=before.registry_path,
                        sets={"international/zz2": {"region": "international", "set": "zz2", "serie": "zz",
                                                    "languages": {}}},
                        cards={"international/zz2": {"region": "international", "set": "zz2",
                                                     "cards": [{**card("zz2-1")}]}})
    after.stamp(before)
    assert after.sets["international/zz2"]["uuid"] == before.sets["international/zz1"]["uuid"]
    assert after.cards["international/zz2"]["cards"][0]["uuid"] == old


def test_a_printing_keeps_its_uuid_when_its_version_key_changes(tmp_path):
    stamped = [{"key": "staff", "promoTypes": [{"name": "staff", "category": "stamp"}], "finishes": ["holo"],
                "identifiers": {"tcgdexVariantIds": {"holo": "s1"}}, "printings": {"en": {}}}]
    before = write_spine(tmp_path, [card("zz1-1", versions=stamped)])
    old = printings(before.cards["international/zz1"]["cards"][0])[0]["uuid"]
    renamed = copy.deepcopy(stamped)
    renamed[0].update(key="staff-stamp", promoTypes=[{"name": "staff-stamp", "category": "stamp"}])
    after = copy.deepcopy(before)
    after.cards["international/zz1"]["cards"][0]["versions"] = renamed
    after.stamp(before)
    assert printings(after.cards["international/zz1"]["cards"][0])[0]["uuid"] == old


def test_an_oracle_keeps_its_uuid_when_tcgdex_fixes_its_text(tmp_path):
    before = write_spine(tmp_path, [card("zz1-1", attack="Thundr Shock")])
    old = before.cards["international/zz1"]["cards"][0]["oracleId"]
    after = copy.deepcopy(before)
    after.cards["international/zz1"]["cards"][0]["attacks"][0]["name"] = {"en": "Thunder Shock"}
    after.stamp(before)
    assert after.cards["international/zz1"]["cards"][0]["oracleId"] == old


def test_the_spine_errors_name_a_wrong_uuid(tmp_path):
    spine = write_spine(tmp_path, [card("zz1-1")])
    registry = uuids.load_registry(spine.registry_path)
    assert uuids.errors(spine, registry) == []
    spine.cards["international/zz1"]["cards"][0]["versions"][0]["printings"]["en"]["uuid"] = str(uuids.NAMESPACE)
    assert any(e.startswith("printings international/zz1-1~en: uuid") for e in uuids.errors(spine, registry))


# --- links --------------------------------------------------------------------------------------------------------


def _box(*items):
    return {"id": "zz1-box", "region": "international", "set": "zz1", "category": "other", "name": "Box",
            "contentsStatus": "complete", "contents": {"cards": list(items)},
            "releases": [{"language": "en", "name": "Box", "sources": ["https://example.com/"]}]}


def test_a_products_card_must_be_a_printing_with_its_tcgplayer_product(tmp_path):
    versions = [{"finishes": ["holo"], "identifiers": {"tcgdexVariantIds": {"holo": "v1"}},
                 "printings": {"en": {"identifiers": {"tcgplayerProductIds": {"holo": 7}}}}}]
    good = {"tcgdexCardId": "zz1-1", "tcgdexVariantId": "v1", "tcgplayerProductId": 7, "count": 1, "role": "promo"}
    spine = write_spine(tmp_path, [card("zz1-1", versions=versions)], [_box(good)])
    assert spine_module.link_errors(spine) == []
    spine.families = [Family(spine.families[0].path, _box({**good, "tcgdexVariantId": "v9"},
                                                          {**good, "tcgplayerProductId": 8}))]
    errors = spine_module.link_errors(spine)
    assert any("no printing of international/zz1-1 has TCGdex variant v9" in e for e in errors)
    assert any("names TCGplayer product 8" in e for e in errors)
