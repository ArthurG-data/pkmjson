"""pokemon.com product pages: names without the brand, pack counts in every language, dates, and the name match."""
from pathlib import Path

from import_pokemon_com import Catalog, launch_day, product_names, stated_packs
from pkmjson import Family


def _family(fid, name, category="collection_box", set_id="sv08", sealed=()):
    return Family(Path(f"{fid}.json"), {
        "id": fid, "region": "international", "set": set_id, "category": category, "name": name,
        "contents": {"sealed": list(sealed)}, "releases": [{"language": "en", "name": name, "sources": ["x"]}]})


def test_names_lose_the_brand_and_a_two_product_title_splits():
    assert product_names("Pokémon-Sammelkartenspiel: Top-Trainer-Box Karmesin & Purpur – Stürmische Funken") == [
        "Top-Trainer-Box Karmesin & Purpur – Stürmische Funken"]
    assert product_names("Pokémon Sammelkartenspiel:Schillerndes Rayquaza-EX-Box") == ["Schillerndes Rayquaza-EX-Box"]
    assert product_names("Set Allenatore Fuoriclasse dell’espansione Zenit Regale del GCC Pokémon") == [
        "Set Allenatore Fuoriclasse dell’espansione Zenit Regale"]
    assert product_names("Pokémon TCG: Shining Fates Premium Collection—Shiny Crobat VMAX "
                         "Pokémon TCG: Shining Fates Premium Collection—Shiny Dragapult VMAX") == [
        "Shining Fates Premium Collection—Shiny Crobat VMAX", "Shining Fates Premium Collection—Shiny Dragapult VMAX"]


def test_pack_counts_read_digits_and_words_and_skip_sleeves():
    assert stated_packs(["9 Pokémon TCG: Scarlet & Violet—Surging Sparks booster packs", "65 card sleeves"], "en") == 9
    assert stated_packs(["Dieci buste dellʼespansione Destino Splendente", "65 bustine protettive con Eevee"], "it") == 10
    assert stated_packs(["4 paquetes de mejora de Pokémon GO"], "es") == 4
    assert stated_packs(["9 Boosterpacks der Pokémon-Sammelkartenspiel-Erweiterung"], "de") == 9
    assert stated_packs(["A never-before-seen foil promo card featuring Bewear-GX"], "en") == 0


def test_launch_day_reads_full_dates_only():
    assert launch_day("Launch: November 08, 2024") == "2024-11-08"
    assert launch_day("Data di uscita: 8 novembre 2024") == "2024-11-08"
    assert launch_day("Lanzamiento: 8 de noviembre de 2024") == "2024-11-08"
    assert launch_day("Veröffentlichung: Q4 2024") is None


def test_variants_on_one_page_all_match_and_a_set_bundle_or_another_mechanic_never_does():
    catalog = Catalog([
        _family("zacian", "True Steel Premium Collection [Zacian]"),
        _family("zamazenta", "True Steel Premium Collection [Zamazenta]"),
        _family("tins", "True Steel Premium Collection [Set of 2]", category="other"),
        _family("v-deck", "V Battle Deck [Melmetal V]", category="battle_deck"),
    ])
    families, _ = catalog.match("True Steel Premium Collection")
    assert sorted(f.data["id"] for f in families) == ["zacian", "zamazenta"]
    assert catalog.match("Melmetal ex Battle Deck")[0] == []
