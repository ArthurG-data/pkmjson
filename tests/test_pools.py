"""contents.pool: the schema and validator rule, its generation, and build carrying it into every release."""
import json
from pathlib import Path

from import_pools import OUT_OF_SCOPE, check_mapping, pool_for, with_pool
from import_tcgplayer import keep_pool
from pkmjson import flatten, load, validate

ROOT = Path(__file__).resolve().parents[1]
TCGDEX = {"international": {"sm115", "sma", "sv08"}, "asia": {"SV8"}}


def _pack(fid="zz-booster-pack", set_="sv08", *, region="international", category="booster_pack", pool=None,
          languages=("en",), notes=None):
    contents = {"pool": pool} if pool is not None else {}
    data = {
        "id": fid, "region": region, "set": set_, "category": category, "name": fid, "contentsStatus": "partial",
        "contents": contents,
        "releases": [{"language": lang, "name": f"{fid} {lang}", "sources": ["https://example.com/"]}
                     for lang in languages],
    }
    if notes:
        data["notes"] = notes
    return data


def _write(tmp_path, *families):
    for f in families:
        path = tmp_path / f["region"] / f["set"] / f"{f['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(f), encoding="utf-8")
    return load(tmp_path)


# --- schema and validator ---------------------------------------------------------------------------------------


def test_a_booster_pack_may_carry_a_pool(tmp_path):
    pack = _pack(pool=[{"set": "sv08"}, {"set": "sma", "region": "international"}])
    assert validate(_write(tmp_path, pack), tmp_path) == []


def test_a_sleeved_pack_may_carry_a_pool(tmp_path):
    assert validate(_write(tmp_path, _pack(category="sleeved_booster_pack", pool=[{"set": "sv08"}])), tmp_path) == []


def test_a_box_may_not_carry_a_pool(tmp_path):
    box = _pack("zz-box", category="booster_box", pool=[{"set": "sv08"}])
    assert validate(_write(tmp_path, box), tmp_path) == [
        "international/sv08/zz-box.json: contents.pool is only for booster packs, not booster_box"]


def test_a_release_pool_is_checked_like_the_family_pool(tmp_path):
    box = _pack("zz-box", category="booster_box")
    box["releases"][0]["contents"] = {"pool": [{"set": "sv08"}]}
    assert validate(_write(tmp_path, box), tmp_path) == [
        "international/sv08/zz-box.json: en contents.pool is only for booster packs, not booster_box"]


def test_a_pool_may_not_be_empty_or_hold_unknown_keys(tmp_path):
    errors = validate(_write(tmp_path, _pack(pool=[])), tmp_path)
    assert len(errors) == 1 and "contents/pool" in errors[0]
    errors = validate(_write(tmp_path, _pack(pool=[{"set": "sv08", "odds": 0.1}])), tmp_path)
    assert len(errors) == 1 and "odds" in errors[0]


def test_a_pool_may_not_name_a_set_twice_even_with_the_region_spelled_out(tmp_path):
    assert validate(_write(tmp_path, _pack(pool=[{"set": "sv08"}, {"set": "sv08"}])), tmp_path)
    pack = _pack(pool=[{"set": "sv08"}, {"set": "sv08", "region": "international"}])
    assert validate(_write(tmp_path, pack), tmp_path) == [
        "international/sv08/zz-booster-pack.json: contents.pool names international/sv08 twice"]


def test_the_same_set_code_in_another_region_is_not_a_duplicate(tmp_path):
    pack = _pack(pool=[{"set": "sv08"}, {"set": "sv08", "region": "asia"}])
    assert validate(_write(tmp_path, pack), tmp_path) == []


# --- generation -------------------------------------------------------------------------------------------------


def test_a_pack_holds_its_own_set():
    assert pool_for(_pack(), TCGDEX, {}, {}) == ([{"set": "sv08"}], None)


def test_a_subset_tcgdex_files_as_its_own_set_joins_the_pool():
    pack = _pack("sm115-booster-pack", "sm115")
    assert pool_for(pack, TCGDEX, {"international/sm115": ["sma"]}, {}) == (
        [{"set": "sm115"}, {"set": "sma"}], None)


def test_a_subset_applies_only_to_its_own_region():
    pack = _pack("zz-pack", "SV8", region="asia")
    assert pool_for(pack, TCGDEX, {"international/SV8": ["sma"]}, {}) == ([{"set": "SV8"}], None)


def test_a_pack_of_a_set_tcgdex_does_not_list_gets_no_pool():
    pool, why = pool_for(_pack("zz-pack", "zz9"), TCGDEX, {}, {})
    assert pool is None and why == "zz9 is not a TCGdex en set"
    pool, why = pool_for(_pack("zz-pack", "sv08", region="asia"), TCGDEX, {}, {})
    assert pool is None and why == "sv08 is not a TCGdex ja set"


def test_an_excluded_family_gets_no_pool():
    assert pool_for(_pack(), TCGDEX, {}, {"zz-booster-pack": "a bundle"}) == (None, "a bundle")


def test_a_mapped_set_must_exist_in_tcgdex():
    assert check_mapping({"extraSets": {"international/sm115": ["sma"]}}, TCGDEX) == []
    assert check_mapping({"extraSets": {"international/sm115": ["nope"]}}, TCGDEX) == [
        "mappings/pack_pools.json: international/sm115 names nope, which TCGdex does not list"]


def test_with_pool_replaces_the_out_of_scope_note_and_is_stable():
    pack = _pack(notes=f"Booster pack cards are random. {OUT_OF_SCOPE}")
    once = with_pool(pack, [{"set": "sv08"}])
    assert once["contents"] == {"pool": [{"set": "sv08"}]}
    assert OUT_OF_SCOPE not in once["notes"] and once["notes"].startswith("Booster pack cards are random.")
    assert with_pool(once, [{"set": "sv08"}]) == once


def test_a_skipped_pack_loses_a_stale_pool():
    assert with_pool(_pack(pool=[{"set": "zz9"}]), None)["contents"] == {}


def test_the_published_pools_name_tcgdex_sets_and_known_subsets():
    mapping = json.loads((ROOT / "mappings" / "pack_pools.json").read_text(encoding="utf-8"))
    assert mapping["extraSets"]["international/sm115"] == ["sma"]
    assert mapping["extraSets"]["international/swsh4.5"] == ["swsh4.5sv"]
    assert mapping["extraSets"]["international/cel25"] == ["cel25cc"]
    families = {f.data["id"]: f.data for f in load(ROOT / "data")}
    assert families["sm115-booster-pack"]["contents"]["pool"] == [{"set": "sm115"}, {"set": "sma"}]
    assert "pool" not in families["svp-2-booster-packs-celebi-collector-s-pin"]["contents"]


# --- rebuilds ---------------------------------------------------------------------------------------------------


def test_regenerating_a_pack_keeps_its_pool():
    fresh = _pack()
    keep_pool(fresh, _pack(pool=[{"set": "sv08"}, {"set": "sma"}]))
    assert fresh["contents"]["pool"] == [{"set": "sv08"}, {"set": "sma"}]


def test_regenerating_a_box_does_not_gain_a_pool():
    box = _pack("zz-box", category="booster_box")
    keep_pool(box, _pack(pool=[{"set": "sv08"}]))
    assert box["contents"] == {}


# --- build ------------------------------------------------------------------------------------------------------


def test_build_carries_the_pool_into_every_release_sorted_with_regions_spelled_out(tmp_path):
    pack = _pack(pool=[{"set": "sma"}, {"set": "sv08"}, {"set": "A1", "region": "asia"}], languages=("en", "fr"))
    out = flatten(_write(tmp_path, pack))
    expected = [{"set": "A1", "region": "asia"}, {"set": "sma", "region": "international"},
                {"set": "sv08", "region": "international"}]
    assert out["zz-booster-pack:en"]["contents"]["pool"] == expected
    assert out["zz-booster-pack:fr"]["contents"]["pool"] == expected


def test_a_release_with_its_own_contents_still_gets_the_family_pool(tmp_path):
    pack = _pack(pool=[{"set": "sv08"}], languages=("en", "fr"))
    pack["releases"][1]["contents"] = {"other": [{"name": "Code card", "count": 1}]}
    out = flatten(_write(tmp_path, pack))
    assert out["zz-booster-pack:fr"]["contents"]["pool"] == [{"set": "sv08", "region": "international"}]
    assert out["zz-booster-pack:fr"]["contents"]["other"] == [{"name": "Code card", "count": 1}]


def test_a_product_without_a_pool_has_no_pool_key(tmp_path):
    out = flatten(_write(tmp_path, _pack("zz-box", category="booster_box")))
    assert "pool" not in out["zz-box:en"]["contents"]
