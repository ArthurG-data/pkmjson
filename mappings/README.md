# Mappings

Lookup tables the import tools read. Each row is a fact another source states; nothing here is copied prose.

- `tcgplayer_groups.json`: TCGplayer group id → TCGdex set (`region`, `set`). Exported on 2026-10-21 from
  AutoMana's catalogue, which maps groups by voting with the singles whose TCGdex variant names the TCGplayer
  product. Groups TCGplayer made for products TCGdex has no set for are left out.
- `cardmarket_sealed.json`: TCGplayer sealed product id → Cardmarket product id, exported on 2026-10-21 from
  AutoMana's Cardmarket matcher (name tiers within a set, ambiguous matches dropped). Cardmarket sells every
  language of a sealed product under one id, so the id is written on the product family.
- `pack_pools.json`: hand-kept input of `tools/import_pools.py`. `extraSets` maps `<region>/<set>` to the TCGdex sets,
  filed apart from it, that a booster pack of that set also holds: `international/sm115` → `sma` (Hidden Fates Shiny
  Vault), `swsh4.5` → `swsh4.5sv`, `cel25` → `cel25cc`, `swsh12.5` → `swsh12.5gg` (Galarian Gallery), the Trainer
  Galleries `swsh9tg` to `swsh12tg`, and `ex10` → `exu` (Unown Collection). Add a subset only when TCGdex lists it as
  a set id of its own and it is not already part of the main set (Legendary Treasures already holds its Radiant
  Collection cards). `skip` maps a family id to why it gets no pool: bundles of packs from several sets that
  TCGplayer files under a promo set. The tool refuses a mapped id TCGdex does not list.
