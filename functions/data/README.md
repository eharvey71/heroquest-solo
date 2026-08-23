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
- `artifacts.json` — id -> {name, text} for the ten 1989 Artifact Cards,
  transcribed verbatim from the owner's physical cards. Feeds quest
  PLACEMENT only right now (which artifact a `find_artifact` objective
  names as its goal, or which chest holds one as loot along the way --
  see `validator.artifacts` and `generator.prompt`'s ARTIFACTS section)
  and lets the LLM's own prose reference the real name/effect. The
  schema's optional `artifactId` properties (objective.target and
  furniture.contains) are generated FROM this catalog and would be
  omitted entirely if it were empty, so the mechanism degrades safely
  to a no-op if the catalog is ever cleared.

  None of the ten cards' actual EFFECTS are enforced yet -- that's a
  separate, unbuilt piece, same shape as hero_spells.py was before it
  existed. Sorted by whether an effect is even a candidate for digital
  enforcement, per CLAUDE.md's boundary:
  - Touches state the app already tracks, so COULD be applied digitally
    if built: Ring of Return (teleports hero tokens to the stairway --
    positions are digital), Spell Ring and Wand of Magic (both bend the
    "one spell, once per quest" rule hero_spells.py already enforces
    via spellsCast), Elixir of Life (revives a hero -- alive/dead is
    digital per engine/heroes.py, Body/Mind Points are not).
  - Physical-only, same as any other weapon or armor card: Talisman of
    Lore (Mind Points), Spirit Blade, Borin's Armor, Orc's Bane,
    Wizard's Cloak (all hero combat-dice counts), Wizard's Staff
    (combat dice + diagonal strike -- already permitted generically for
    any hero weapon, see CLAUDE.md's hero-attack adjacency notes).
