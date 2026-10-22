import json
from pathlib import Path

import pytest

from pkmjson import flatten, load, validate, validate_cards

ROOT = Path(__file__).resolve().parents[1]


def _family(fid, *, region="international", set_="zz1", sealed=(), cards=(), languages=("en",)):
    return {
        "id": fid, "region": region, "set": set_, "category": "other", "name": fid, "contentsStatus": "complete",
        "contents": {"sealed": [{"product": p, "count": n} for p, n in sealed], "cards": list(cards)},
        "releases": [{"language": lang, "name": f"{fid} {lang}", "sources": ["https://example.com/"]}
                     for lang in languages],
    }


def _write(tmp_path, *families):
    for f in families:
        path = tmp_path / f["region"] / f["set"] / f"{f['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(f), encoding="utf-8")
    return load(tmp_path)


def test_the_published_data_is_valid():
    data = ROOT / "data"
    assert validate(load(data), data) == []


def test_a_nested_product_needs_a_release_in_the_same_language(tmp_path):
    families = _write(tmp_path, _family("zz-pack", languages=("en",)),
                      _family("zz-box", sealed=[("zz-pack", 36)], languages=("en", "fr")))
    assert validate(families, tmp_path) == [
        "international/zz1/zz-box.json: fr contains zz-pack, which has no fr release"]


def test_unknown_products_wrong_paths_and_cycles_are_reported(tmp_path):
    families = _write(tmp_path, _family("zz-a", sealed=[("zz-b", 1)]), _family("zz-b", sealed=[("zz-a", 1)]),
                      _family("zz-c", sealed=[("zz-missing", 1)]))
    errors = validate(families, tmp_path)
    assert "international/zz1/zz-c.json: en contains unknown product zz-missing" in errors
    assert any("products contain each other: zz-a -> zz-b -> zz-a" in e for e in errors)


def test_a_japanese_release_belongs_to_the_asia_region(tmp_path):
    families = _write(tmp_path, _family("zz-a", languages=("ja",)))
    assert validate(families, tmp_path) == [
        "international/zz1/zz-a.json: language ja does not belong to region international"]


def test_a_file_must_sit_at_region_set_id(tmp_path):
    (tmp_path / "international" / "other").mkdir(parents=True)
    (tmp_path / "international" / "other" / "zz-a.json").write_text(json.dumps(_family("zz-a")), encoding="utf-8")
    assert validate(load(tmp_path), tmp_path) == [
        "international/other/zz-a.json: should live at international/zz1/zz-a.json"]


def test_flatten_gives_one_entry_per_language_with_nested_products_in_that_language(tmp_path):
    families = _write(tmp_path, _family("zz-pack", languages=("en", "fr")),
                      _family("zz-box", sealed=[("zz-pack", 36)], languages=("en", "fr")))
    out = flatten(families)
    assert list(out) == ["zz-box:en", "zz-box:fr", "zz-pack:en", "zz-pack:fr"]
    assert out["zz-box:fr"]["contents"]["sealed"] == [{"product": "zz-pack:fr", "count": 36}]
    assert out["zz-box:fr"]["name"] == "zz-box fr"


def test_every_language_carries_the_family_cardmarket_id(tmp_path):
    box = _family("zz-box", languages=("en", "fr"))
    box["identifiers"] = {"cardmarketProductId": 784949}
    box["releases"][0]["identifiers"] = {"tcgplayerProductIds": [565606]}
    out = flatten(_write(tmp_path, box))
    assert out["zz-box:en"]["identifiers"] == {"cardmarketProductId": 784949, "tcgplayerProductIds": [565606]}
    assert out["zz-box:fr"]["identifiers"] == {"cardmarketProductId": 784949}


def test_a_release_cannot_carry_a_cardmarket_id(tmp_path):
    box = _family("zz-box")
    box["releases"][0]["identifiers"] = {"cardmarketProductId": 784949}
    errors = validate(_write(tmp_path, box), tmp_path)
    assert len(errors) == 1 and "cardmarketProductId" in errors[0]


CARD = {"tcgdexCardId": "svp-159", "tcgdexVariantId": "v1", "tcgplayerProductId": 594386, "count": 1, "role": "promo"}


@pytest.mark.parametrize("variants, expected", [
    ([{"variantId": "v1", "thirdParty": {"tcgplayer": 594386}}], []),
    ([{"variantId": "v2"}], ["international/zz1/zz-etb.json: svp-159 has no variant v1"]),
    ([{"variantId": "v1", "thirdParty": {"tcgplayer": 1}}],
     ["international/zz1/zz-etb.json: svp-159 tcgplayerProductId is 594386, TCGdex says 1"]),
])
def test_cards_are_checked_against_tcgdex(tmp_path, variants, expected):
    families = _write(tmp_path, _family("zz-etb", cards=[CARD]))
    assert validate_cards(families, tmp_path, fetch=lambda lang, cid: {"variants_detailed": variants}) == expected


def test_a_card_tcgdex_does_not_have_is_reported(tmp_path):
    families = _write(tmp_path, _family("zz-etb", cards=[CARD]))
    assert validate_cards(families, tmp_path, fetch=lambda lang, cid: None) == [
        "international/zz1/zz-etb.json: TCGdex has no card svp-159"]
