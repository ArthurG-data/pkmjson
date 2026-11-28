"""UUIDs: given once, kept for good, the same however often the tools run."""
import copy
import uuid

import pytest

import uuids
from pkmjson import Family


def _family(fid, *products, languages=("en",), cardmarket=None):
    family = {"id": fid, "region": "international", "set": "zz1", "category": "other", "name": fid,
              "contentsStatus": "partial", "contents": {},
              "releases": [{"language": lang, "name": fid, "sources": ["https://example.com/"]} for lang in languages]}
    if products:
        family["releases"][0]["identifiers"] = {"tcgplayerProductIds": list(products)}
    if cardmarket:
        family["identifiers"] = {"cardmarketProductId": cardmarket}
    return family


def _run(registry, *families):
    uuids.assign(families, registry)
    return {f["id"]: f["uuid"] for f in families}


def test_a_record_seen_first_gets_uuid5_of_its_kind_and_id():
    family = _family("zz1-box", 7, languages=("en", "fr"))
    assert _run(uuids.empty(), family) == {"zz1-box": str(uuid.uuid5(uuids.NAMESPACE, "products:zz1-box"))}
    assert [r["uuid"] for r in family["releases"]] == [
        str(uuid.uuid5(uuids.NAMESPACE, f"productReleases:zz1-box:{lang}")) for lang in ("en", "fr")]


def test_the_namespace_is_pkmjsons_own():
    assert uuids.NAMESPACE == uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/ArthurG-data/pkmjson")


def test_a_rebuild_from_nothing_gives_every_record_the_uuid_it_had():
    def build():
        return [_family("zz1-box", 7), _family("zz1-pack", languages=("en", "fr"))]
    one, two = build(), build()
    uuids.assign(one, uuids.empty())
    uuids.assign(two, uuids.empty())
    assert one == two


def test_a_second_run_changes_nothing():
    registry, families = uuids.empty(), [_family("zz1-box", 7), _family("zz1-pack")]
    uuids.assign(families, registry)
    before = copy.deepcopy((families, registry))
    uuids.assign(families, registry)
    assert (families, registry) == before


def test_the_uuid_sits_right_after_the_id_and_the_language():
    family = _family("zz1-box", 7)
    _run(uuids.empty(), family)
    assert list(family)[:2] == ["id", "uuid"] and list(family["releases"][0])[:2] == ["language", "uuid"]


def test_a_renamed_family_keeps_its_uuid_through_its_tcgplayer_product():
    registry = uuids.empty()
    was = _run(registry, _family("sm10-booster-pack-576913", 576913))
    now = _run(registry, _family("asia-sm10-booster-pack", 576913))
    assert now["asia-sm10-booster-pack"] == was["sm10-booster-pack-576913"]


def test_a_renamed_release_keeps_its_uuid_with_its_family():
    registry = uuids.empty()
    old, new = _family("zz1-old", 7, languages=("en", "fr")), _family("zz1-new", 7, languages=("en", "fr"))
    _run(registry, old)
    _run(registry, new)
    assert [r["uuid"] for r in new["releases"]] == [r["uuid"] for r in old["releases"]]


def test_a_family_that_loses_its_listing_keeps_its_uuid_through_its_id():
    registry = uuids.empty()
    was = _run(registry, _family("zz1-box", 7))
    assert _run(registry, _family("zz1-box")) == was


def test_two_families_that_swap_names_keep_their_own_uuids():
    registry = uuids.empty()
    was = _run(registry, _family("zz1-a", 1), _family("zz1-b", 2))
    now = _run(registry, _family("zz1-b", 1), _family("zz1-a", 2))
    assert now == {"zz1-b": was["zz1-a"], "zz1-a": was["zz1-b"]}


def test_a_family_that_leaves_and_returns_gets_its_uuid_back():
    registry = uuids.empty()
    was = _run(registry, _family("zz1-box", 7))
    _run(registry, _family("zz1-other", 8))
    assert _run(registry, _family("zz1-box", 7)) == was


def test_a_uuid_is_never_given_to_another_family():
    registry = uuids.empty()
    was = _run(registry, _family("zz1-box", 7))
    # A new product under the old id while the old product still exists elsewhere.
    now = _run(registry, _family("zz1-box-7", 7), _family("zz1-box", 9))
    assert now["zz1-box-7"] == was["zz1-box"] and now["zz1-box"] != was["zz1-box"]


def test_two_live_families_claiming_one_uuid_are_a_conflict():
    registry = uuids.empty()
    _run(registry, _family("zz1-a", 1, 2))
    with pytest.raises(uuids.Conflict):
        _run(registry, _family("zz1-a", 1), _family("zz1-b", 1))


def test_errors_name_a_missing_a_wrong_and_a_shared_uuid():
    registry, families = uuids.empty(), [_family("zz1-a", 1), _family("zz1-b", 2)]
    uuids.assign(families, registry)
    spine = uuids.Spine(families=[Family(None, f) for f in families])
    assert uuids.errors(spine, registry) == []
    families[1]["uuid"] = families[0]["uuid"]
    del families[0]["releases"][0]["uuid"]
    errors = uuids.errors(spine, registry)
    assert any("productReleases zz1-a:en has no uuid" in e for e in errors)
    assert any("products zz1-b: uuid" in e for e in errors)
    assert any(e.startswith(f"products: uuid {families[0]['uuid']} is on 2 records") for e in errors)


def test_history_errors_catch_a_dropped_or_changed_uuid():
    before = uuids.empty()
    _run(before, _family("zz1-a", 1), _family("zz1-b", 2))
    after = copy.deepcopy(before)
    assert uuids.history_errors(before, after) == []
    after["products"]["keys"].pop("tcgplayer:1")
    after["products"]["keys"]["tcgplayer:2"] = str(uuid.uuid4())
    errors = uuids.history_errors(before, after)
    assert len(errors) == 2 and "dropped" in errors[0] and "changed" in errors[1]


def test_the_registry_saved_is_sorted_and_reloads_the_same(tmp_path):
    registry = uuids.empty()
    _run(registry, _family("zz1-b", 2), _family("zz1-a", 1))
    uuids.save_registry(registry, tmp_path)
    text = (tmp_path / "products.json").read_text()
    assert uuids.load_registry(tmp_path) == registry
    uuids.save_registry(uuids.load_registry(tmp_path), tmp_path)
    assert (tmp_path / "products.json").read_text() == text
