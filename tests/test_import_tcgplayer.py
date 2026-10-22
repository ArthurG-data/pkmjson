"""Regressions from the import audits: each test is a product text the generator once got wrong."""
from import_tcgplayer import (EDITIONS, Draft, Group, Parser, PromoResolver, classify, expansion_of, fold, is_sealed,
                              list_items, merge_release)


def test_a_basic_energy_without_card_fields_is_a_card_but_an_energy_product_is_not():
    assert not is_sealed({"name": "Water Energy (Unnumbered) (No E Reader)"})
    assert not is_sealed({"name": "Basic Fire Energy"})
    assert is_sealed({"name": "Pokemon TCG: Energy Booster Pack"})
    assert is_sealed({"name": "Scarlet & Violet Elite Trainer Box"})


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
M1L = _group(7, "M1L", "M1L: Mega Brave")
S5A = _group(8, "S5a", "S5a: Matchless Fighters")
GROUPS = [SV01, SV10_5B, SV10_5W, XY12, SV08_5, XY1, M1L, S5A]
CHILD = {(g.group_id, "booster_pack"): f"{g.set_id}-booster-pack" for g in GROUPS}
CHILD[(SV08_5.group_id, "booster_box")] = "sv08.5-booster-box"
CHILD[(S5A.group_id, "booster_box")] = "s5a-booster-box"


def _parse(group, name, text, category=None, edition=EDITIONS[3]):
    parser = Parser({g.expansion: g for g in GROUPS}, CHILD, {}, NoPromos())
    product = {"productId": 1, "name": name, "extendedData": [{"name": edition.text_field, "value": text}]}
    draft = Draft(product, group, "x", category or classify(name), edition)
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


def test_a_japanese_product_reads_its_description():
    box = _parse(M1L, "Mega Brave Booster Box",
                 "Each sealed <em>Japanese</em> Mega Brave Booster Box contains 30 booster packs containing 5 random "
                 "cards each.", edition=EDITIONS[85])
    assert box.sealed == [{"product": "M1L-booster-pack", "count": 30}] and box.complete


def test_boosters_are_packs_and_a_named_booster_box_is_a_product():
    trainer_box = _parse(M1L, "Premium Trainer Box MEGA Brave", "• 10 Mega Brave Boosters\n• 1 Card Box")
    assert trainer_box.sealed == [{"product": "M1L-booster-pack", "count": 10}]
    assert trainer_box.other == [{"name": "Card Box", "count": 1}]
    bundle = _parse(S5A, "Matchless Fighters Klara and Avery Set",
                    "• 1 Japanese Matchless Fighters booster box\n• 2 Set of sleeves featuring Klara and Avery")
    assert bundle.sealed == [{"product": "s5a-booster-box", "count": 1}]


def test_an_item_that_names_no_accessory_is_not_other():
    bundle = _parse(SV01, "Kanto Friends Collection", "• 1 coin\n• Raichu\n• Machamp")
    assert [o["name"] for o in bundle.other] == ["Coin"]
    assert [u["line"] for u in bundle.unresolved] == ["Raichu", "Machamp"]
    trainer_box = _parse(SV01, "Premium Trainer Box ex",
                         "• Assortment of popular Pokémon, Trainer, Energy cards\n• 1 coin\n• 1 Pokémon TCG Energy cards")
    assert [o["name"] for o in trainer_box.other] == ["Coin", "Pokémon TCG Energy cards"]
    assert not trainer_box.complete


def test_a_deck_is_not_other_but_its_code_card_is():
    box = _parse(SV01, "GX Challenge Box", "• 1 Ready-to-play theme deck\n• 1 Code card to play this deck online")
    assert [o["name"] for o in box.other] == ["Code card to play this deck online"]
    assert not box.complete


def test_random_and_promos_are_never_other():
    file_set = _parse(SV01, "Collection File Set", "• Cards are randomly included in 5 pieces each\n• 3 Promos")
    assert file_set.other == [] and len(file_set.unresolved) == 2


def test_a_starter_set_is_a_deck():
    assert classify("ex Starter Set Pikachu ex & Pawmot") == "battle_deck"
    assert classify("Start Deck 100 Battle Collection") == "battle_deck"


def test_a_store_bundle_of_two_products_lists_nothing():
    for name in ("Costco Evolving Skies Elite Trainer Box and Tin", "Paldea Legends Tins [Bundle of 2]"):
        bundle = _parse(SV01, name, "• 8 Scarlet & Violet booster packs\n• 65 card sleeves")
        assert bundle.sealed == [] and bundle.other == [] and not bundle.complete


def test_a_product_that_always_holds_packs_is_not_complete_without_them():
    tin = _parse(SV01, "Galar Power Mini Tin [Dragapult]", "• 1 Metallic Pokemon coin")
    assert [o["name"] for o in tin.other] == ["Metallic Pokemon coin"] and not tin.complete
    blister = _parse(SV01, "Mythical 2-Pack Blister [Celebi]", "• 1 Scarlet & Violet booster pack\n• 1 coin")
    assert not blister.complete


def test_a_rerun_keeps_the_name_and_date_another_tool_gave_the_release():
    generated = {"language": "ja", "name": "Pokemon Card 151 Booster Pack", "identifiers": {"tcgplayerProductIds": [1]},
                 "sources": ["https://www.tcgplayer.com/product/1"]}
    named = {**generated, "name": "強化拡張パック「ポケモンカード151」", "releaseDate": "2023-06-16",
             "sources": generated["sources"] + ["https://www.pokemon-card.com/products/index.html?keyword=151"]}
    assert merge_release(generated, named) == {k: named[k] for k in
                                               ("language", "name", "releaseDate", "identifiers", "sources")}
    assert merge_release(generated, generated) == generated
