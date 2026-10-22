"""The official Japanese list's names and dates, and the set match that keeps TCGdex's misnamed sets out."""
import datetime as dt
from collections import defaultdict

from pathlib import Path

from import_pokemon_card_jp import SetIndex, clean_title, key, pack_name, pokemon_matches, release_day
from pkmjson import Family


def _sets(*rows):
    index = SetIndex.__new__(SetIndex)
    index.by_key = defaultdict(list)
    for set_id, name, day in rows:
        index.by_key[key(name)].append((set_id, dt.date.fromisoformat(day)))
    return index


def test_titles_lose_markup_and_names_lose_readings_and_product_words():
    assert clean_title("拡張パック「スカーレット<big>ex</big >」") == "拡張パック「スカーレットex」"
    assert key(pack_name("強化拡張パック「ポケモンカード151（イチゴーイチ）」")) == key("ポケモンカード151")
    assert key("強化パック ロストリンク") == key(pack_name("強化パック「ロストリンク」"))


def test_release_day_reads_the_japanese_date():
    assert release_day("2026年 7月31日（金）") == "2026-07-31"
    assert release_day("") is None


def test_a_set_matches_only_with_its_name_and_a_date_within_a_week():
    # TCGdex names SV4a (Shiny Treasure ex, 2023-12-01) after Raging Surf (SV3a, 2023-09-22).
    sets = _sets(("SV3a", "レイジングサーフ", "2023-09-22"), ("SV4a", "レイジングサーフ", "2023-12-01"))
    assert sets.find("レイジングサーフ", "2023-09-22") == "SV3a"
    assert sets.find("シャイニートレジャーex", "2023-12-01") is None
    assert sets.find("レイジングサーフ", "2024-03-01") is None


SPECIES = {"lugia": "ルギア", "tyranitar": "バンギラス", "eevee": "イーブイ", "pikachu": "ピカチュウ"}


def _family(fid, name):
    return Family(Path(f"{fid}.json"), {"id": fid, "name": name, "set": "SV-P", "category": "battle_deck"})


def _product(title):
    return {"productTitle": title, "kind": "construction"}


def test_a_deck_matches_the_official_product_naming_its_pokemon_and_kind():
    deck = _family("lugia", "Generations Start Deck - Lugia ex & Tyranitar ex")
    official = [_product("スタートデッキGenerations ルギアex・バンギラスex"), _product("スターターセットex ルギアex")]
    assert [(f.data["id"], p["productTitle"]) for f, p in pokemon_matches([deck], official, SPECIES)] == [
        ("lugia", "スタートデッキGenerations ルギアex・バンギラスex")]


def test_a_match_that_is_not_one_to_one_is_left_out():
    official = [_product("スターターセットex イーブイex"), _product("スターターセット テラスタル イーブイex")]
    assert pokemon_matches([_family("eevee", "Starter Set ex Eevee ex")], official, SPECIES) == []
    one = [_product("スターターセットex ピカチュウex")]
    twins = [_family("a", "Starter Set ex Pikachu ex"), _family("b", "Pikachu ex Starter Set")]
    assert pokemon_matches(twins, one, SPECIES) == []
