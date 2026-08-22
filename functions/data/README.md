# data/

Static, code-owned catalogs the validator (and later the generator prompt)
load at runtime.

- `board.json` — synced verbatim from `design/board.json`, the ground-truth
  board geometry (see CLAUDE.md). If the design copy changes, re-copy it
  here; this directory is what actually ships with the Cloud Function.
- `monsters.json` — 1989 NA base stats, from design/quest-schema.md. Threat
  cost is *not* stored here; it's computed as `attack + defend + body` per
  CLAUDE.md's Balance system, so it can't drift from the stats.
  `chaos_warlock` is not in the rulebook's eight-row monster table —
  the figure stands in for named quest villains whose stats are printed
  in that quest's own notes. Its row here is Balur the Fire Mage
  (Quest 8): Move 8 / Attack 2 / Defend 5 / Body 3 / Mind 7, threat 10.
  Balur is the lighter of the two book Warlocks; the Witch Lord
  (Quest 14, Move 10 / Attack 5 / Defend 6 / Body 4 / Mind 6, threat 15)
  is what the named-monster `overrides` are for, so the catalog row
  stays the floor rather than the ceiling.
  `caster: true` marks the three types that may carry Chaos spells —
  the owner's 4 chaos warriors, 1 chaos warlock and 1 gargoyle. See
  `validator.balance.caster_types`.
- `furniture.json` — footprints + owned physical counts, from CLAUDE.md's
  Physical component caps section.
