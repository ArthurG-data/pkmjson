"""Regressions from the import audits: each test is a product text the generator once got wrong."""
from import_tcgplayer import Draft, Group, Parser, PromoResolver, classify, expansion_of, fold, list_items


class NoPromos(PromoResolver):
    def __init__(self):
        self.by_name = {}


def _group(group_id, set_id, name):
    return Group(group_id, set_id, name, expansion_of(name), serie="sv")


SV01 = _group(1, "sv01", "SV01: Scarlet & Violet Base Set")
SV10_5B = _group(2, "sv10.5b", "SV: Black Bolt")
SV10_5W = _group(3, "sv10.5w", "SV: White Flare")
XY12 = _group(4, "xy12", "XY - Evolutions")
SV08_5 = _group(5, "sv08.5", "SV: Prismatic Evolutions")
XY1 = _group(6, "xy1", "XY Base Set")
GROUPS = [SV01, SV10_5B, SV10_5W, XY12, SV08_5, XY1]
CHILD = {(g.group_id, "booster_pack"): f"{g.set_id}-booster-pack" for g in GROUPS}
CHILD[(SV08_5.group_id, "booster_box")] = "sv08.5-booster-box"


def _parse(group, name, text, category=None):
    parser = Parser({g.expansion: g for g in GROUPS}, CHILD, {}, NoPromos())
    product = {"productId": 1, "name": name, "extendedData": [{"name": "CardText", "value": text}]}
    draft = Draft(product, group, "x", category or classify(name))
    parser.parse(draft)
    return draft


def test_fold_keeps_words_apart_across_an_em_dash():
    assert fold("Scarlet & Violet—Surging Sparks") == "scarlet violet surging sparks"


def test_group_names_lose_their_series_prefix_and_base_set():
    assert expansion_of("SM - Crimson Invasion") == "crimson invasion"
    assert expansion_of("SWSH01: Sword & Shield Base Set") == "sword shield"


def test_the_expansion_beats_a_series_name_and_a_shorter_name_inside_it():
    blister = _parse(SV10_5B, "Black Bolt Mini Tin", "• 2 Pokémon TCG: Scarlet & Violet—Black Bolt booster packs")
    assert blister.sealed == [{"product": "sv10.5b-booster-pack", "count": 2}]
    tin = _parse(SV08_5, "Prismatic Evolutions Mini Tin", "• 2 Prismatic Evolutions booster packs")
    assert tin.sealed == [{"product": "sv08.5-booster-pack", "count": 2}]


def test_a_random_or_series_only_pack_is_not_a_base_set_pack():
    pin = _parse(XY12, "XY Evolutions Pin Collection", "• 1 random XY booster pack")
    assert pin.sealed == [] and pin.unresolved
    collection = _parse(XY12, "XY Evolutions Collection", "• 2 XY booster packs")
    assert collection.sealed == []


def test_respectively_takes_the_products_own_set():
    binder = _parse(SV10_5B, "Black Bolt Binder Collection",
                    "• 5 Black Bolt or White Flare booster packs, respectively")
    assert binder.sealed == [{"product": "sv10.5b-booster-pack", "count": 5}]


def test_an_each_pack_clause_is_cut_and_the_rest_kept():
    assert list_items("36 booster packs, each containing 10 cards and 1 basic Energy") == ["36 booster packs"]
    box = _parse(SV08_5, "Prismatic Evolutions Booster Box",
                 "Each booster box contains 36 booster packs (each pack contains 10 random cards).")
    assert box.sealed == [{"product": "sv08.5-booster-pack", "count": 36}]


def test_alternatives_stay_one_item_and_an_accessory_tail_splits():
    assert list_items("1 foil promo card featuring Sylveon, Leafeon, or Glaceon") == [
        "1 foil promo card featuring Sylveon, Leafeon, or Glaceon"]
    assert list_items("1 TCGO Code, Coin") == ["1 TCGO Code", "1 Coin"]


def test_cards_never_land_in_other():
    blister = _parse(SV01, "Scarlet & Violet Premium Checklane Blister",
                     "• 1 Scarlet & Violet booster pack\n• 3 Cards\n• 1 coin")
    assert [o["name"] for o in blister.other] == ["Coin"]
    assert not blister.complete


def test_a_case_counts_its_units_once_and_keeps_its_qualifier():
    case = _parse(SV08_5, "Prismatic Evolutions Booster Box Case",
                  "Each sealed booster box case contains 6 booster boxes of 36 booster packs.")
    assert case.sealed == [{"product": "sv08.5-booster-box", "count": 6}]


def test_a_set_of_several_products_lists_nothing():
    pair = _parse(SV01, "Scarlet & Violet Elite Trainer Box [Set of 2]", "• 9 Scarlet & Violet booster packs")
    assert pair.sealed == [] and not pair.complete


def test_a_pokemon_center_product_with_the_standard_text_is_not_trusted():
    etb = _parse(SV01, "Scarlet & Violet Pokemon Center Elite Trainer Box", "• 9 Scarlet & Violet booster packs")
    assert not etb.complete
