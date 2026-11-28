import collections
import json
import re
from pathlib import Path

import pytest

import uuids
from conftest import write_families
from pkmjson import (
    SEALED,
    UUIDS,
    file_errors,
    flatten,
    is_plain_pack,
    load,
    official_set_names,
    printings,
    set_prefix,
    validate,
    validate_cards,
)

ROOT = Path(__file__).resolve().parents[1]


def _family(fid, *, region="international", set_="zz1", sealed=(), cards=(), languages=("en",)):
    contents = {k: v for k, v in (("sealed", [{"product": p, "count": n} for p, n in sealed]),
                                  ("cards", list(cards))) if v}
    return {
        "id": fid, "region": region, "set": set_, "category": "other", "name": fid,
        "contentsStatus": "complete" if contents else "partial", "contents": contents,
        "releases": [{"language": lang, "name": f"{fid} {lang}", "sources": ["https://example.com/"]}
                     for lang in languages],
    }


_write = write_families


def test_the_published_products_are_valid():
    assert validate(load(SEALED), SEALED, sets=json.loads((ROOT / "sets" / "sets.json").read_text())) == []


def test_a_nested_product_needs_a_release_in_the_same_language(tmp_path):
    families = _write(tmp_path, _family("zz1-pack", languages=("en",)),
                      _family("zz1-box", sealed=[("zz1-pack", 36)], languages=("en", "fr")))
    assert validate(families, tmp_path) == [
        "international/zz1/zz1-box.json: fr contains zz1-pack, which has no fr release"]


def test_unknown_products_wrong_paths_and_cycles_are_reported(tmp_path):
    families = _write(tmp_path, _family("zz1-a", sealed=[("zz1-b", 1)]), _family("zz1-b", sealed=[("zz1-a", 1)]),
                      _family("zz1-c", sealed=[("zz1-missing", 1)]))
    errors = validate(families, tmp_path)
    assert "international/zz1/zz1-c.json: en contains unknown product zz1-missing" in errors
    assert any("products contain each other: zz1-a -> zz1-b -> zz1-a" in e for e in errors)


def test_a_japanese_release_belongs_to_the_asia_region(tmp_path):
    families = _write(tmp_path, _family("zz1-a", languages=("ja",)))
    assert validate(families, tmp_path) == [
        "international/zz1/zz1-a.json: language ja does not belong to region international"]


def test_a_file_must_sit_at_region_set_id(tmp_path):
    family = _family("zz1-a")
    uuids.assign([family], uuids.empty())
    (tmp_path / "international" / "other").mkdir(parents=True)
    (tmp_path / "international" / "other" / "zz1-a.json").write_text(json.dumps(family), encoding="utf-8")
    assert validate(load(tmp_path), tmp_path) == [
        "international/other/zz1-a.json: should live at international/zz1/zz1-a.json"]


def test_flatten_gives_one_entry_per_language_with_nested_products_in_that_language(tmp_path):
    families = _write(tmp_path, _family("zz1-pack", languages=("en", "fr")),
                      _family("zz1-box", sealed=[("zz1-pack", 36)], languages=("en", "fr")))
    out = flatten(families)
    assert list(out) == ["zz1-box:en", "zz1-box:fr", "zz1-pack:en", "zz1-pack:fr"]
    assert out["zz1-box:fr"]["contents"]["sealed"] == [{"product": "zz1-pack:fr", "count": 36}]
    assert out["zz1-box:fr"]["name"] == "zz1-box fr"


def test_every_language_carries_the_family_cardmarket_id(tmp_path):
    box = _family("zz1-box", languages=("en", "fr"))
    box["identifiers"] = {"cardmarketProductId": 784949}
    box["releases"][0]["identifiers"] = {"tcgplayerProductIds": [565606]}
    out = flatten(_write(tmp_path, box))
    assert out["zz1-box:en"]["identifiers"] == {"cardmarketProductId": 784949, "tcgplayerProductIds": [565606]}
    assert out["zz1-box:fr"]["identifiers"] == {"cardmarketProductId": 784949}


def test_a_release_cannot_carry_a_cardmarket_id(tmp_path):
    box = _family("zz1-box")
    box["releases"][0]["identifiers"] = {"cardmarketProductId": 784949}
    errors = validate(_write(tmp_path, box), tmp_path)
    assert len(errors) == 1 and "cardmarketProductId" in errors[0]


CARD = {"tcgdexCardId": "svp-159", "tcgdexVariantId": "v1", "tcgplayerProductId": 594386, "count": 1, "role": "promo"}


@pytest.mark.parametrize("variants, expected", [
    ([{"variantId": "v1", "thirdParty": {"tcgplayer": 594386}}], []),
    ([{"variantId": "v2"}], ["international/zz1/zz1-etb.json: svp-159 has no variant v1"]),
    ([{"variantId": "v1", "thirdParty": {"tcgplayer": 1}}],
     ["international/zz1/zz1-etb.json: svp-159 tcgplayerProductId is 594386, TCGdex says 1"]),
])
def test_cards_are_checked_against_tcgdex(tmp_path, variants, expected):
    families = _write(tmp_path, _family("zz1-etb", cards=[CARD]))
    assert validate_cards(families, tmp_path, fetch=lambda lang, cid: {"variants_detailed": variants}) == expected


def test_a_card_tcgdex_does_not_have_is_reported(tmp_path):
    families = _write(tmp_path, _family("zz1-etb", cards=[CARD]))
    assert validate_cards(families, tmp_path, fetch=lambda lang, cid: None) == [
        "international/zz1/zz1-etb.json: TCGdex has no card svp-159"]


# --- ids, sets and owners ---------------------------------------------------------------------------------------


def test_an_id_starts_with_its_sets_prefix(tmp_path):
    families = _write(tmp_path, _family("zz2-box"))
    assert validate(families, tmp_path) == [
        "international/zz1/zz2-box.json: id zz2-box should start with zz1-, its set's prefix"]


def test_an_asia_set_that_shares_an_international_id_takes_the_asia_prefix(tmp_path):
    families = _write(tmp_path, _family("zz1-box"), _family("zz1-pack", region="asia", set_="ZZ1", languages=("ja",)),
                      _family("asia-zz1-box", region="asia", set_="ZZ1", languages=("ja",)))
    assert validate(families, tmp_path) == [
        "asia/ZZ1/zz1-pack.json: id zz1-pack should start with asia-zz1-, its set's prefix"]


def test_a_family_set_must_be_in_sets_json(tmp_path):
    families = _write(tmp_path, _family("zz1-box"))
    sets = {"international/zz9": {"region": "international", "set": "zz9", "languages": {}}}
    assert validate(families, tmp_path, sets=sets) == [
        "international/zz1/zz1-box.json: set international/zz1 is not in sets/sets.json: run tools/import_sets.py"]


def test_one_tcgplayer_or_cardmarket_product_sells_one_family(tmp_path):
    a, b = _family("zz1-a"), _family("zz1-b")
    for f in (a, b):
        f["identifiers"] = {"cardmarketProductId": 5}
        f["releases"][0]["identifiers"] = {"tcgplayerProductIds": [7]}
    assert validate(_write(tmp_path, a, b), tmp_path) == [
        "international/zz1/zz1-a.json: Cardmarket product 5 is also on zz1-b",
        "international/zz1/zz1-a.json: TCGplayer product 7 is also on zz1-b"]


def test_a_product_listed_twice_in_one_contents_is_reported(tmp_path):
    box = _family("zz1-box", sealed=[("zz1-pack", 1)])
    box["contents"]["sealed"].append({"product": "zz1-pack", "count": 2})
    errors = validate(_write(tmp_path, _family("zz1-pack"), box), tmp_path)
    assert errors == ["international/zz1/zz1-box.json: en lists zz1-pack twice: give it one count"]


def test_every_family_and_release_needs_a_uuid(tmp_path):
    (tmp_path / "international" / "zz1").mkdir(parents=True)
    (tmp_path / "international" / "zz1" / "zz1-a.json").write_text(json.dumps(_family("zz1-a")), encoding="utf-8")
    errors = validate(load(tmp_path), tmp_path)
    assert any("'uuid' is a required property" in e for e in errors)


def test_set_prefixes_and_plain_packs():
    assert set_prefix("asia", "SM1+") == "sm1plus"
    assert set_prefix("asia", "SM10", {"sm10", "sv08"}) == "asia-sm10"
    assert set_prefix("international", "sm10", {"sm10"}) == "sm10"
    assert is_plain_pack({"id": "asia-sm10-booster-pack", "region": "asia", "set": "SM10", "category": "booster_pack"})
    assert is_plain_pack({"id": "sv08-booster", "region": "international", "set": "sv08", "category": "booster_pack"})
    assert not is_plain_pack({"id": "sm6-3-card-booster-pack", "region": "international", "set": "sm6",
                              "category": "booster_pack"})


def test_official_set_names_skip_a_language_with_only_a_logo(tmp_path):
    path = tmp_path / "sets.json"
    path.write_text(json.dumps({
        "asia/SVAL": {"region": "asia", "set": "SVAL", "languages": {"ja": {"logo": "https://x/l.png"}}},
        "international/sv08": {"region": "international", "set": "sv08", "languages": {
            "fr": {"name": "Étincelles Déferlantes", "source": "https://www.pokemon.com/fr/x"},
            "es": {"name": "Chispas", "source": "https://api.tcgdex.net/v2/es/sets/sv08"}}}}), encoding="utf-8")
    assert official_set_names(path) == {("international", "sv08", "fr"): "Étincelles Déferlantes"}


def test_the_committed_sets_mappings_and_registry_match_their_schemas():
    assert file_errors(registry=UUIDS) == []


def test_the_readme_counts_are_the_datas():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    families = [f.data for f in load(SEALED)]
    releases = collections.Counter(r["language"] for f in families for r in f["releases"])
    regions = collections.Counter(f["region"] for f in families)
    stated = re.search(r"The data also holds (\d+) product families in (\d+) language releases\. (\d+) "
                       r"families are international and\s+(\d+) are Japanese\.", readme)
    assert stated and tuple(map(int, stated.groups())) == (
        len(families), sum(releases.values()), regions["international"], regions["asia"])
    names = {"English": "en", "French": "fr", "Japanese": "ja", "German": "de", "Italian": "it", "Spanish": "es"}
    by_language = dict((names[m.group(2)], int(m.group(1)))
                       for m in re.finditer(r"(\d+) (English|French|Japanese|German|Italian|Spanish)", readme))
    assert by_language == dict(releases)
    complete = re.search(r"(\d+) families list their whole contents", readme)
    assert int(complete.group(1)) == sum(f["contentsStatus"] == "complete" for f in families)


def test_the_readme_counts_of_the_spine_are_the_datas():
    import uuids
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    spine = uuids.Spine.load()
    cards = [(b["region"], c) for b in spine.cards.values() for c in b["cards"]]
    flat = [p for _, c in cards for p in printings(c)]
    regions = collections.Counter(r for r, _ in cards)
    stated = re.search(r"The data holds (\d+) sets in (\d+) series, and (\d+) cards: (\d+) international and (\d+) "
                       r"Asian\. They are (\d+) oracles\s+and (\d+) printings\. (\d+) printings carry a TCGplayer "
                       r"product and (\d+) a Cardmarket product\.", readme)
    assert stated and tuple(map(int, stated.groups())) == (
        len(spine.sets), len(spine.series), len(cards), regions["international"], regions["asia"],
        len({c["oracleId"] for _, c in cards}), len(flat),
        sum(bool((p.get("identifiers") or {}).get("tcgplayerProductIds")) for p in flat),
        sum(bool((p.get("identifiers") or {}).get("cardmarketProductIds")) for p in flat))
