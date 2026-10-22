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
`<id>:<language>` (`sv08-etb:fr`). Each entry's `identifiers` holds the family's ids and the release's. Tagged releases attach that file to a GitHub release.

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
