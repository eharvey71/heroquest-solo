# data/

Static, code-owned catalogs the validator (and later the generator prompt)
load at runtime.

- `board.json` — synced verbatim from `design/board.json`, the ground-truth
  board geometry (see CLAUDE.md). If the design copy changes, re-copy it
  here; this directory is what actually ships with the Cloud Function.
- `monsters.json` — 1989 NA base stats, from design/quest-schema.md. Threat
  cost is *not* stored here; it's computed as `attack + defend + body` per
  CLAUDE.md's Balance system, so it can't drift from the stats.
  `chaos_warlock` is intentionally omitted — CLAUDE.md caps it at 1
  (boss-only) but no base stats for it exist in any design doc. A quest
  can't use it as a monster type until stats are added here.
- `furniture.json` — footprints + owned physical counts, from CLAUDE.md's
  Physical component caps section.
