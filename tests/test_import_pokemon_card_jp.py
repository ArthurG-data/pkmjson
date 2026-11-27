"""The official Japanese list's names and dates, and the set match that keeps TCGdex's misnamed sets out."""
import datetime as dt
from collections import defaultdict
from pathlib import Path

from import_pokemon_card_jp import (
    SEARCH_PAGE,
    SetIndex,
    clean_title,
    key,
    name_release,
    names_in,
    pack_name,
    pokemon_matches,
    release_day,
)
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


def test_a_name_counts_only_where_it_is_not_the_start_of_a_longer_name():
    assert names_in("ミュウ", "スターターセット ミュウex")
    assert not names_in("ミュウ", "スターターセット テラスタル ミュウツーex")
    assert names_in("ゲンガー", "スターターセットMEGA メガゲンガーex")
    assert names_in("ゾロア", "スターターセットex ゾロア＆ゾロアークex")


def test_naming_a_release_keeps_its_other_sources_and_replaces_its_old_search_page():
    old_search = SEARCH_PAGE + "keyword=old"
    family = Family(None, {"releases": [{"language": "ja", "uuid": "u", "name": "Booster",
                                         "sources": ["https://www.tcgplayer.com/product/1", "https://example.com/",
                                                     old_search]}]})
    product = {"kind": "expansion", "productTitle": "拡張パック「バトルパートナーズ」", "releaseDate": "2025年1月24日"}
    assert name_release(family, product)
    release = family.data["releases"][0]
    assert release["sources"][:2] == ["https://www.tcgplayer.com/product/1", "https://example.com/"]
    assert len(release["sources"]) == 3 and release["sources"][2] != old_search
    assert release["uuid"] == "u" and release["releaseDate"] == "2025-01-24"
    assert not name_release(family, product)
