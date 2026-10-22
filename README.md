# pkmjson

An open dataset of sealed Pokémon TCG products and what is inside them: the booster packs in a booster box,
the packs, promo cards and accessories in an Elite Trainer Box, and so on, for every language a product was
sold in. Card, set and listing data are already published elsewhere (TCGdex, pokemon-tcg-data, TCGCSV);
this dataset covers product contents, which none of them publish.

## Layout

One file per product family, at `data/<region>/<set>/<id>.json`:

- `region` is the TCGdex tree, `international` or `asia`. Japanese, Korean and Chinese products are their own
  families, because their sets and cards differ from the international ones.
- `set` is the TCGdex set id (`sv08`, `SV8`).
- `id` is the stable pkmjson id of the product, without language (`sv08-etb`).

A family lists its `contents` once and its `releases`, one per language. Each release has its own name, release
date, TCGplayer ids and the sources that state its contents. A release can carry its own `contents` when that
language's box differs. The Cardmarket id sits on the family, because Cardmarket sells every language of a sealed
product under one product and records the language on each offer.

```json
{
  "id": "sv08-etb",
  "region": "international",
  "set": "sv08",
  "category": "elite_trainer_box",
  "identifiers": {"cardmarketProductId": 784963},
  "contents": {
    "sealed": [{"product": "sv08-booster", "count": 9}],
    "cards": [{"tcgdexCardId": "svp-159", "tcgdexVariantId": "jr7oetx1mqug9",
               "tcgplayerProductId": 594386, "cardmarketProductId": 796935, "count": 1, "role": "promo"}],
    "other": [{"name": "Card sleeves", "count": 65}]
  },
  "releases": [{"language": "en", "name": "Surging Sparks Elite Trainer Box", "identifiers": {"tcgplayerProductIds": [565630]}, "sources": ["..."]},
               {"language": "fr", "name": "Coffret Dresseur d'Élite Écarlate et Violet – Étincelles Déferlantes", "sources": ["..."]}]
}
```

- **Cards** are pinned to one printing by TCGdex card id and TCGdex variant id. The variant id is the same in
  every language, and it tells a stamped promo apart from the plain one. Each card also carries the TCGplayer
  and Cardmarket product ids of that printing, which `validate.py --online` checks against TCGdex.
- **Nested products** (`sealed`) point at another family. They resolve to the same language as the release that
  holds them, so a French booster box holds French booster packs.
- **`contentsStatus`** is `partial` when the file cannot list everything, for example a booster pack's random
  cards. Which cards a pack can hold is out of scope.

The full format is `schema/product.schema.json`.

## Build output

`python tools/build.py` writes `dist/AllProducts.json`, with one entry per product and language, keyed
`<id>:<language>` (`sv08-etb:fr`). It also writes `dist/AllSets.json`, a copy of `sets/sets.json`. That file gives
each set's name as printed on its packs and a logo, per language, keyed `<region>/<set>`. Each value cites its
source. `logoSource` says where the logo comes from. `logoLanguage` marks a logo borrowed from another language
because the set has none of its own. `logoKind` marks a product image or set symbol used where no logo exists. Each entry's `identifiers` holds the family's ids and the release's. Tagged releases attach that file to a GitHub release.

## Where the data comes from

- **English and Japanese contents:** `tools/import_tcgplayer.py` reads TCGplayer's product text through tcgcsv.com,
  from category 3 for English and, with `--category 85`, category 85 for Japanese. A file stays `partial` when the text
  leaves something out or names something the tool cannot pin to a product or card. What was left over goes to
  `review/tcgplayer-<category>.json`.
- **Japanese names and dates:** `tools/import_pokemon_card_jp.py` matches pokemon-card.com's product search to
  those families. A match requires both the TCGdex set's name and its release date. Where it matches, the `ja`
  release gets the official name, date and search page.
- **French releases:** `tools/import_pokepedia.py` reads Poképédia's product pages.
- **German, Italian, Spanish and more French releases:** pokemon.com's product gallery links each US product page
  to its other-language versions. pokemon.com refuses scripted clients, so `tools/pokemon_com_crawl.js` runs in a
  browser tab on www.pokemon.com and returns the pages as JSON. `tools/import_pokemon_com.py --crawl <file>` then
  matches each US page to its family by English name. It adds a release only when that language's page states the
  same number of booster packs as the US page.
- **Set names and logos:** `tools/import_sets.py` builds `sets/sets.json` from three sources. pokemon.com's
  expansion lists come first (fetched in a browser by `tools/pokemon_com_expansions.js`). pokemon-card.com's pack
  names cover Japanese. TCGdex fills what both leave out. The tool also names each set's own booster pack, in every
  language, after the set as printed on the pack: "Karmesin & Purpur – Stürmische Funken", not a name assembled
  from a dictionary word and a set name.

A file whose notes do not start with "Generated from TCGplayer" was written by hand, and the import tools leave it
alone.

## Development

```
uv sync
uv run pytest
uv run python tools/validate.py --online
uv run python tools/build.py
```

## Adding a product

Add the file, cite at least one page that states the contents in `sources`, and run `validate.py --online`.
Contents are facts. Do not copy product descriptions or images.

## Licence

The data and schema are CC BY 4.0 (`LICENSE-DATA`). The tools are MIT (`LICENSE`). Pokémon and its trademarks
belong to Nintendo, Creatures Inc. and GAME FREAK inc.; this project is not affiliated with them.
