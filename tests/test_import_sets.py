"""Sets: the pokemon.com values sets.json keeps, and which pack is a set's own."""
from pathlib import Path

from import_sets import plain_pack, recorded_official
from pkmjson import Family


def _pack(fid, set_id="sm6"):
    return Family(Path(f"{fid}.json"), {"id": fid, "set": set_id, "category": "booster_pack"})


def test_recorded_pokemon_com_values_are_kept_without_borrowed_logos():
    page = "https://www.pokemon.com/de/pokemon-sammelkartenspiel/karmesin-purpur-sturmische-funken"
    sets = {"international/sv08": {"region": "international", "set": "sv08", "languages": {
        "de": {"name": "Karmesin & Purpur – Stürmische Funken", "source": page, "releaseDate": "2024-11-08",
               "logo": "https://www.pokemon.com/static-assets/de.png", "logoSource": "pokemon.com"},
        "it": {"name": "Scarlatto e Violetto – Scintille Folgoranti", "source": page.replace("/de/", "/it/"),
               "logo": "https://www.pokemon.com/static-assets/de.png", "logoSource": "pokemon.com",
               "logoLanguage": "de"},
        "fr": {"name": "Étincelles Déferlantes", "source": "https://api.tcgdex.net/v2/fr/sets/sv08"}}}}
    assert recorded_official(sets) == {"sv08": {
        "de": {"name": "Karmesin & Purpur – Stürmische Funken", "releaseDate": "2024-11-08", "source": page,
               "logo": "https://www.pokemon.com/static-assets/de.png"},
        "it": {"name": "Scarlatto e Violetto – Scintille Folgoranti", "source": page.replace("/de/", "/it/")}}}


def test_a_sets_own_pack_is_not_its_3_card_pack():
    assert plain_pack([_pack("sm6-3-card-booster-pack"), _pack("sm6-booster-pack")]).data["id"] == "sm6-booster-pack"
    assert plain_pack([_pack("SM1+".lower().replace("+", "plus") + "-booster-pack", "SM1+")]).data["set"] == "SM1+"
    assert plain_pack([_pack("sm6-mini-booster-pack"), _pack("sm6-3-card-booster-pack")]) is None
