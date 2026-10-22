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
  cards.
- **`contents.pool`** is on booster packs (`booster_pack`, `sleeved_booster_pack`) only. It lists the sets whose cards
  the pack can hold, as `{"set": "sm115"}` entries, each with an optional `region` that defaults to the family's. A
  pack can contain any card of those sets, in the release's language, as TCGdex lists each set. The cards are random,
  so the pool says nothing about rarity slots or odds, and it does not change `contentsStatus`. Most packs hold their
  own set. Some also hold a subset TCGdex files as a set of its own: a Hidden Fates pack lists `sm115` and `sma` (the
  Shiny Vault). A pack whose set TCGdex does not list has no pool. `build.py` writes the pool into every release of
  the pack, sorted by region and set, with the region spelled out.

```json
"contents": {"pool": [{"set": "sm115"}, {"set": "sma"}]}
```

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
  `review/tcgplayer-<category>.json`. Products TCGplayer files outside any expansion ("Miscellaneous Cards &
  Products", World Championships decks) go under the promo set of the era they were released in, such as `svp` or
  `swshp`, because that is where their promo cards are.
- **Japanese names and dates:** `tools/import_pokemon_card_jp.py` matches pokemon-card.com's product search to
  those families. A match requires both the TCGdex set's name and its release date. A deck or set with no set of its
  own matches instead by the Pokémon it is named after (translated with PokéAPI's species names) and the kind of
  product. Where it matches, the `ja` release gets the official name, date and search page.
- **French releases:** `tools/import_pokepedia.py` reads Poképédia's product pages through its MediaWiki API and
  takes each product's French name, release date and, where the French box differs, its packs. Each release
  credits its page (see `NOTICE`).
- **German, Italian, Spanish and more French releases:** the names and dates of these releases come from
  pokemon.com's product pages, which each release cites. They are kept as recorded. pokemon.com's terms forbid
  downloading its content in bulk, so no tool fetches them again.
- **Set names and logos:** `tools/import_sets.py` builds `sets/sets.json`. The names printed on the packs come from
  pokemon.com's expansion pages (kept as recorded) and, for Japanese, pokemon-card.com's pack names. TCGdex fills
  what both leave out. Logos are links: TCGdex's logo for the language first, then pokemon.com's, then for Japanese
  the image of the pokemon-card.com product. The tool also names each set's own booster pack, in every language,
  after the set as printed on the pack: "Karmesin & Purpur – Stürmische Funken", not a name assembled from a
  dictionary word and a set name.

A file whose notes do not start with "Generated from TCGplayer" was written by hand, and the import tools leave it
alone.

- **Booster pack pools:** `tools/import_pools.py` gives each pack its `contents.pool` from the pack's `set`, TCGdex's
  set lists (English for `international`, Japanese for `asia`) and `mappings/pack_pools.json`. Run it after
  `import_tcgplayer.py`; it is idempotent and rewrites a pool another tool dropped. `import_tcgplayer.py` also keeps a
  pool it finds in a file it regenerates. Packs it leaves without a pool are listed in `review/pack-pools.json`.

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

The data and schema are CC BY 4.0 (`LICENSE-DATA`). The tools are MIT (`LICENSE`). `NOTICE` covers the facts
taken from Poképédia and the logo links. Pokémon and its trademarks
belong to Nintendo, Creatures Inc. and GAME FREAK inc.; this project is not affiliated with them.
