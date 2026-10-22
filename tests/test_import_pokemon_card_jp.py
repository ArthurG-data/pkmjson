"""The official Japanese list's names and dates, and the set match that keeps TCGdex's misnamed sets out."""
import datetime as dt
from collections import defaultdict

from import_pokemon_card_jp import SetIndex, clean_title, key, pack_name, release_day


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
