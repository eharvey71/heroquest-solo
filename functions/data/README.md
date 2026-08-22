# data/

Static, code-owned catalogs the validator (and later the generator prompt)
load at runtime.

- `board.json` — synced verbatim from `design/board.json`, the ground-truth
  board geometry (see CLAUDE.md). If the design copy changes, re-copy it
  here; this directory is what actually ships with the Cloud Function.
- `monsters.json` — 1989 NA base stats, from design/quest-schema.md. Threat
  cost is *not* stored here; it's computed as `attack + defend + body` per
  CLAUDE.md's Balance system, so it can't drift from the stats.
  `chaos_warlock`'s stats are a HOUSE BASELINE, not transcribed: the
  1989 rulebook's monster table has eight entries and the Warlock is
  not among them — the figure is used for named quest villains whose
  stats are printed in that quest's notes. Move 6 / Attack 2 / Defend 4
  / Body 3 / Mind 6 (threat 9) makes him frail in a swing and hard to
  put to sleep, so his threat comes from the Chaos cards he carries. A
  quest that wants him tougher uses the named-monster `overrides`.
  Replace these numbers if the quest book gives a better base.
  `caster: true` marks the three types that may carry Chaos spells —
  the owner's 4 chaos warriors, 1 chaos warlock and 1 gargoyle. See
  `validator.balance.caster_types`.
- `furniture.json` — footprints + owned physical counts, from CLAUDE.md's
  Physical component caps section.
