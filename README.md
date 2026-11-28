# pkmjson

An open dataset of the Pokémon TCG, in the spirit of Scryfall and MTGJSON: every set, card and printing that TCGdex
lists, in every language, and the sealed products and what is inside them. Every record has a pkmjson UUID that is
given once and never changes, so a program can key on it.

Cards and sets come from a pinned commit of TCGdex's cards-database. pkmjson groups their variants into printings,
groups reprints of one card under an oracle id, and ties each printing to the TCGplayer and Cardmarket products that
sell it. The sealed products come from TCGplayer's product text, pokemon-card.com, Poképédia and pokemon.com. They
are what no other source publishes: the booster packs in a booster box, the packs, promo cards and accessories in an
Elite Trainer Box, and so on.

The data holds 559 sets in 39 series, and 41967 cards: 23841 international and 18126 Asian. They are 26355 oracles
and 167318 printings. 29910 printings carry a TCGplayer product and 135402 a Cardmarket product.

The data also holds 3189 product families in 4445 language releases. 2905 families are international and
284 are Japanese. By language, the releases are 2905 English, 553 French, 284 Japanese, 249 German, 230 Italian and
224 Spanish. 454 families list their whole contents.

## Using the data

Each tagged release attaches six files to a GitHub release, each with its JSON schema beside it
(`AllSets.schema.json`, ...):

| File | Keyed by | Holds |
|---|---|---|
| `AllSets.json` | `<region>/<set>` (`international/sv08`) | the set's UUID, its series (id, UUID, names), TCGplayer group and Cardmarket expansion ids, TCGdex's names, dates, card count and abbreviations, and per language the name printed on its packs and a logo |
| `AllCards.json` | `<region>/<card id>` (`international/sv08-001`) | the card's UUID, its oracle id, its set and set UUID, its number, its gameplay facts and text in every language, its legality (`legal`, and `banned`: the formats that ban it by name), and the keys of its printings |
| `AllPrintings.json` | `<region>/<printing id>` (`international/sv08-001~fr`) | one card in one language and version: its UUID, its card's and oracle's UUIDs, its finishes, promo types, image, TCGdex variant ids, the TCGplayer and Cardmarket product and the CardTrader id of each finish |
| `AllProducts.json` | `<family id>:<language>` (`sv08-etb:fr`) | one sealed product in one language: its UUID, its family's UUID, its contents (each card with its printing's UUID, each pool set with its UUID) and the sources that state them |
| `AllUuids.json` | kind, then UUID | every UUID and the natural key of its record: a set's or series' `<region>/<code>`, a card's key and oracle id, a printing's card key, language and version key, an oracle's cards, a product release's key and family UUID. It is 19 MB, for a reader that only needs to match its own rows to pkmjson's UUIDs |
| `AllTranslations.json` | language, then enum | the word TCGdex shows, in German, Spanish, French, Italian and Portuguese, for each English enum value. Cards and printings state their category, rarity, stage, types, finishes and so on as TCGdex's English keys; a value this file lacks is shown in English |

Every file is `{"meta": {"version", "date", "sources"}, "data": {...}}`. All six come from one build, so a reader
that downloads them separately can check that the versions agree. `date` is the day the data last changed (the last
commit to `sets/` or `data/`), so one commit always builds the same files. `sources.tcgdex` is the TCGdex commit the
cards come from.

### Regions

TCGdex keeps two trees, and so does pkmjson. `international` holds the sets sold in English and the other Western
languages. `asia` holds the sets sold in Japanese, Korean, Chinese, Thai and Indonesian. The trees reuse ids (both
have a `neo1`), so a set or card is always named with its region. TCG Pocket is international in every language.

### Cards, printings and oracles

- A **card** is one TCGdex card id in one tree: `international/sv08-001`. It is the same card in every language.
- A **printing** is a card in one language and one version. Its id is `<card id>~<language>`. A version other than
  the plain one adds its promo types and size: `international/svp-159~en~pokemon-center`, `…~oversized`. A version
  is what TCGdex's variants of the card carry besides their finish: a stamp, a foil pattern, an edition, a metal or
  lenticular card. `mappings/promo_types.csv` names each of them (AutoMana's table). A printing lists its finishes
  (`nonfoil`, `holo`, `reverse-holo`), or `null` when TCGdex knows no variant of the card. It also carries the TCGdex
  variant, TCGplayer product, Cardmarket product and CardTrader id of each finish. TCGdex knows CardTrader ids
  for a few sets only. A TCGplayer id goes only on the home language's
  printing: English for international, Japanese for Asian. The card-level TCGdex id names the regular printing, so
  it is never given to a stamped version.
- An **oracle** is one gameplay card, whatever its reprints: MTG's oracle id, `oracleId` on a card and a printing.
  `tools/tcgdex.py` groups the cards:
  1. A card with English text starts from a fingerprint of its English rules text.
  2. Reprints whose fingerprints differ only in wording are joined. The wording can be a full stop, an era's
     rewording ("the Defending Pokémon" became "your opponent's Active Pokémon") or text that is at least 85%
     alike. So are reprints whose fingerprints differ only in a field TCGdex left empty on one of them. They must
     share their name, kind, HP, stage and the names, costs and damage of their attacks.
  3. A card with no English text joins the one English oracle with the same language-free fingerprint (numbers,
     types, costs), else it is grouped in its own language in the same way.

  Two Pikachu with other attacks are two oracles, and a TCG Pocket card is never its paper namesake's oracle.
  A Japanese Trainer card has no numbers to match on, so it joins the English oracle only when TCGdex gives it
  English text.

In `data/cards/<region>/<set>.json` a card holds its `versions`. Each version states its promo types, finishes and
ids once, and holds one printing per language: its UUID, its TCGplayer ids, and whatever that language's printing has
of its own. `AllPrintings` lays them out one printing per entry.

## Layout

- `sets/series.json` lists the TCGdex series, keyed `<region>/<serie>`.
- `sets/sets.json` lists every set, keyed `<region>/<set>`. `tools/import_tcgdex.py` writes its `serie`,
  `identifiers` and `tcgdex` facts, and `tools/import_sets.py` writes its `languages`: the name printed on the
  packs and a logo, each citing its source.
- `data/cards/<region>/<set>.json` holds the set's cards, one per line.
- `data/sealed/<region>/<set>/<id>.json` holds one product family.
- `data/uuids/<kind>.json` is the UUID registry.
- `mappings/` holds the hand-kept inputs: the TCGdex commit (`sources.json`), the promo types (`promo_types.csv`), the
  ids TCGdex renamed (`tcgdex_renames.json`), and the TCGplayer and Cardmarket mappings and pack pools.
- `review/` lists what the tools could not decide.
- `schema/` holds a JSON Schema (draft 2020-12) for every one of these files.

A product family lists its `contents` once and its `releases`, one per language. Each release has its own name,
release date, TCGplayer ids and the sources that state its contents. A release can carry its own `contents` when
that language's box differs. The Cardmarket id sits on the family, because Cardmarket sells every language of a
sealed product under one product and records the language on each offer.

```json
{
  "id": "sv08-etb",
  "uuid": "…",
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
  "releases": [{"language": "en", "uuid": "…", "name": "Surging Sparks Elite Trainer Box", "identifiers": {"tcgplayerProductIds": [565630]}, "sources": ["..."]},
               {"language": "fr", "uuid": "…", "name": "Coffret Dresseur d'Élite Écarlate et Violet – Étincelles Déferlantes", "sources": ["..."]}]
}
```

- **Cards** in a product are pinned to one printing by TCGdex card id and TCGdex variant id. The validator checks
  that each is a printing of the spine and that its TCGplayer product is that printing's. `AllProducts` gives each
  card the UUID of its printing in the release's language.
- **Nested products** (`sealed`) point at another family. They resolve to the same language as the release that
  holds them, so a French booster box holds French booster packs.
- **`contentsStatus`** is `partial` when the file cannot list everything, for example a booster pack's random
  cards.
- **`contents.pool`** is on booster packs (`booster_pack`, `sleeved_booster_pack`) only. It lists the sets whose cards
  the pack can hold, as `{"set": "sm115"}` entries, each with an optional `region` that defaults to the family's. A
  pack can contain any card of those sets, in the release's language. The cards are random, so the pool says nothing
  about rarity slots or odds, and it does not change `contentsStatus`. Most packs hold their own set. Some also hold a
  subset TCGdex files as a set of its own: a Hidden Fates pack lists `sm115` and `sma` (the Shiny Vault).

A family's `id` starts with its set's id, lowercased, with a "+" spelled out (`sm1plus-…` for `SM1+`). An asia set
whose id is also an international set's id gets `asia-` in front: Japan's SM10 and the international sm10 are
different sets, so their packs are `asia-sm10-booster-pack` and `sm10-booster-pack`. A file without `generatedBy`
was written by hand, and the import tools leave it alone.

## UUIDs

`tools/uuids.py` gives every record a UUID, and `data/uuids/<kind>.json` records them. A UUID is given once, never
changes and never goes to another record. The namespace is `uuid5(NAMESPACE_URL,
"https://github.com/ArthurG-data/pkmjson")`, and a record seen for the first time gets
`uuid5(NAMESPACE, "<kind>:<record id>")`, so a rebuild from nothing gives the same UUIDs.

A UUID belongs to what a record is, its identity key. A record re-keyed (renamed, renumbered, its text fixed) is
matched to the record it replaces through its aliases, and takes that record's UUID:

| Kind | Identity key | Aliases |
|---|---|---|
| series | `<region>/<serie>` | an entry of `mappings/tcgdex_renames.json` |
| set | `<region>/<set>` | its TCGplayer groups, a rename |
| card | `<region>/<card id>` | `set:<set UUID>/<number>`: a card whose set was renamed |
| printing | `<card UUID>:<language>:<version key>` | its TCGdex variants: a printing whose promo types were renamed |
| oracle | `fingerprint:<sha1 of its rules text>` | its cards' UUIDs: an oracle whose text TCGdex fixed |
| product family | `tcgplayer:<lowest TCGplayer product id>`, else `id:<family id>` | its id, TCGplayer and Cardmarket products |
| product release | `<family UUID>:<language>` | its id, TCGplayer products |

The registry's `keys` only grows. A record that leaves keeps its key, so it gets its UUID back if it returns, and no
other record can take that UUID. Series, sets and products keep their aliases in the registry (`bridges`). Cards,
printings and oracles take them from the files as they were before the run, to keep the registry small. So one of
those re-keyed from one run to the next keeps its UUID, but one that leaves for a run and comes back under another
key does not.

`validate.py --since <ref>` refuses a registry that dropped or changed a UUID the registry at `<ref>` gave. CI runs
it on every pull request and push. Every import tool stamps the UUIDs before it writes. After a hand edit, run
`tools/uuids.py`.

## Where the data comes from

- **Sets, cards and printings:** `tools/sync_tcgdex.sh` checks out TCGdex's cards-database at the commit
  `mappings/sources.json` pins, and `tools/dump_tcgdex.ts` (bun) dumps it with the repository's own variant-id and
  legality code, and copies its ban list (`meta/legals.ts`) and enum translations (`meta/translations`). Unlike
  TCGdex's API, the repository keeps the languages each variant is printed in.
  `tools/import_tcgdex.py` turns the dump into the spine. Placeholder files in the repository (a set file declaring
  another file's set id, cards in no language of their set) are left out and listed in `review/tcgdex.json`.
  `sync_tcgdex.sh --latest` moves the pin forward.
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

- **Booster pack pools:** `tools/import_pools.py` gives each pack its `contents.pool` from the pack's `set`, TCGdex's
  set lists (English for `international`, Japanese for `asia`) and `mappings/pack_pools.json`. Run it after
  `import_tcgplayer.py`; it is idempotent and rewrites a pool another tool dropped. `import_tcgplayer.py` also keeps a
  pool it finds in a file it regenerates. Packs it leaves without a pool are listed in `review/pack-pools.json`.

## Development

```
uv sync --group dev
uv run ruff check tools tests
uv run pytest
tools/sync_tcgdex.sh                        # dump the pinned TCGdex commit to .cache/tcgdex/ (needs git and bun)
uv run python tools/refresh.py              # every importer in order, then uuids.py and validate.py
uv run python tools/check_losses.py         # did the run lose more than a few of anything?
uv run python tools/validate.py --since main
uv run python tools/build.py
```

The import tools read `.cache/` and fetch only what it lacks. `--refresh`, on `refresh.py` or on one tool, fetches
every page again. The fetcher retries a failed request, refuses to cache a page served wrong, and writes each page
whole or not at all. `refresh.py` against an unchanged cache changes nothing.

`check_losses.py` compares counts with a git ref (default `HEAD`) and fails when one falls by more than 2 and by
more than 5%. It counts the families of each set, the releases of each language, complete contents, card items,
pools, and set names and logos. CI runs it on pull requests. A pull request whose title holds `[allow-loss]` skips
it. The online check (`validate.py --online`) compares each card with TCGdex. CI runs it weekly, before a release
and when started by hand, not on every pull request.

## Adding a product

Add the file, cite at least one page that states the contents in `sources`, run `tools/uuids.py`, and run
`validate.py --online`.
Contents are facts. Do not copy product descriptions or images.

## Licence

The data and schema are CC BY 4.0 (`LICENSE-DATA`). The tools are MIT (`LICENSE`). `NOTICE` covers the facts
taken from Poképédia and the logo links. Pokémon and its trademarks
belong to Nintendo, Creatures Inc. and GAME FREAK inc.; this project is not affiliated with them.
