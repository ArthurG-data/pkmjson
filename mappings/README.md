# Mappings

Lookup tables the import tools read. Each row is a fact another source states; nothing here is copied prose.

- `tcgplayer_groups.json`: TCGplayer group id → TCGdex set (`region`, `set`). Exported on 2026-10-21 from
  AutoMana's catalogue, which maps groups by voting with the singles whose TCGdex variant names the TCGplayer
  product. Groups TCGplayer made for products TCGdex has no set for are left out.
- `cardmarket_sealed.json`: TCGplayer sealed product id → Cardmarket product id, exported on 2026-10-21 from
  AutoMana's Cardmarket matcher (name tiers within a set, ambiguous matches dropped). Cardmarket sells every
  language of a sealed product under one id, so the id is written on the product family.
