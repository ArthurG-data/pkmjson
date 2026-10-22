"""Sets: pokemon.com's English names against TCGdex's, and which pack is a set's own."""
from pathlib import Path

from import_sets import english_key, plain_pack
from pkmjson import Family


def _pack(fid, set_id="sm6"):
    return Family(Path(f"{fid}.json"), {"id": fid, "set": set_id, "category": "booster_pack"})


def test_english_names_lose_series_brand_and_ex_prefix():
    assert english_key("Scarlet & Violet—Surging Sparks") == "surging sparks"
    assert english_key("<em>Mega Evolution—Perfect Order</em>") == "perfect order"
    assert english_key("Pokémon TCG: Call of Legends") == "call of legends"
    assert english_key("EX Team Rocket Returns") == "team rocket returns"
    assert english_key("Scarlet & Violet") == "scarlet violet"


def test_a_sets_own_pack_is_not_its_3_card_pack():
    assert plain_pack([_pack("sm6-3-card-booster-pack"), _pack("sm6-booster-pack")]).data["id"] == "sm6-booster-pack"
    assert plain_pack([_pack("SM1+".lower().replace("+", "plus") + "-booster-pack", "SM1+")]).data["set"] == "SM1+"
    assert plain_pack([_pack("sm6-mini-booster-pack"), _pack("sm6-3-card-booster-pack")]) is None
