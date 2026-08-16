# CLAUDE.md — HeroQuest Solo Zargon App

## What this is
A single-user web app that plays Zargon (the evil wizard) so the owner can
play 1989 NA-edition HeroQuest solo/co-op on the physical board. The app
generates AI quests (backstory + board layout), tracks hidden information
(fog of war, traps, secret doors), decides and narrates all Zargon turns,
and rolls Zargon's dice digitally. Hosted on Firebase. One user, no auth
beyond the owner.

## The physical/digital boundary (settled — do not renegotiate)
DIGITAL: quest map + story, fog of war, trap/secret-door locations, monster
positions + body points, all Zargon decisions, Zargon's dice rolls,
turn log/narration.
PHYSICAL: board, minis, hero sheets (BP/MP/gold/inventory), hero dice rolls,
treasure/spell/equipment card decks.
INTERFACE: hero movement entered as a path drag/click-trace on the app board
(required so traps trigger mid-move and Zargon knows positions). Everything
else is a button: open door, search treasure, search traps/secret doors,
attack [target], end turn. The app NEVER asks for movement roll totals,
hero BP, gold, or inventory. Hero rolls their own combat dice and reports
skulls/shields; app applies results to monsters only.

## Rules edition
1989 North American HeroQuest. Varied monster body points (see
monsters.json). Heroes may pass through fellow heroes, not monsters, and
may not end on an occupied square. Treasure searches use the physical
treasure deck; the app only needs to know if a wandering monster is drawn
(button for it). One treasure search per room, app enforces.

## Architecture
- Frontend: React + SVG/Canvas grid, Firebase Hosting. Renders board,
  fog of war, tokens, path input, Zargon narration log.
- State: Firestore. Collections: quests (validated definitions),
  games (runtime state).
- Backend: Python Cloud Functions.
  - generateQuest(params) -> questId: prompt build + LLM call + validate +
    auto-repair + retry loop (max 3) + Firestore write. Client never sees
    an unvalidated quest.
  - Zargon rules engine: deterministic code (movement, target choice,
    combat resolution). LLM is NEVER in the rules path — only quest
    generation and (optional later) flavor narration.

## Design artifacts (in this repo /design)
- board.json — 26x19 grid, 22 rooms, verified square-by-square against the
  owner's physical board. R18 is L-shaped; R20 (4x5) interlocks with it at
  square (17,13). 148 corridor squares. TREAT AS GROUND TRUTH.
- quest-schema.md — data model v0.1. Amendments since writing: doorways and
  stairway are QUEST-owned, not board-owned (1989 board has no printed
  doors); stairway: {room, pos} placed per quest.
- quest-generator-design.md — generator + validator + budget design.
- generator-prompt.md — LLM prompt template v0.1.

## Physical component caps (validator MUST enforce)
Monster minis RECYCLE (dead minis return to the pool — official quests
exceed box counts). So: no per-quest monster totals cap. Instead cap
SIMULTANEOUS exposure: per-type count in any single room <= owned minis
(orc 8, goblin 6, fimir 3, chaos_warrior 4, skeleton 4, zombie 2, mummy 2,
gargoyle 1, chaos_warlock 1 boss-only). At runtime, if a reveal would need
more minis of a type than are free, the app suggests a proxy.
Furniture and doors DO NOT recycle (they stay on the board):
Furniture: table x2, throne x1, alchemist's bench x1, treasure chest x3,
tomb x1, sorcerer's table x1, bookcase x2, rack x1, fireplace x1,
weapons rack x1, cupboard x1.
Footprints (w x h): table/alch bench/sorcerer's table/tomb/rack 3x2;
throne + chest 1x1; bookcase/cupboard/fireplace/weapons rack 3x1.
Doors: 21 (16 open, 5 closed). Tiles: stairs 2x2, blocked squares,
pit traps, falling block traps, secret doors, skulls.
When the app reveals anything with a physical tile (trap sprung, secret
door found, blocked square, stairs), it must show a "place tile"
instruction naming the tile and square(s).

## Balance system (from prior Monte Carlo sim work — "Zargon Deck")
Monster threat cost ≈ attack + defend + body. Budget by heroCount:
4 heroes 100% of baseline, 3 -> 85%, 2 -> 70% (+1 healing potion each),
1 -> 55% (+lone hero takes 2 actions/turn — turn UI must enforce this).
Zargon turn types rolled per turn (replaces physical card deck):
4H: 72/24/4 normal/cunning/wandering. 3H: 76/20/4. 2H: 80/16/4. 1H: 84/12/4.
Cunning turn = focus-fire lowest-threat-to-kill hero, guard objectives.
Sim-tested win rates 79-92% at these ratios (combat + pacing only).
BASELINE CALIBRATED from 4 official quests (owner's maps, icon counts):
The Trial ~119, Rescue of Sir Ragnar ~104, The Fire Mage ~148,
[3rd color map, undead+goblins] ~117. Baseline (4-hero) = 120.
Targets: 4H 120 / 3H 102 / 2H 84 / 1H 66, all +/-10%; hard +15%.
Named bosses (Verag, Balur, Gulthor...) priced as base type + override cost.

## Open items / first tasks
1. Firebase project skeleton (Hosting + Firestore + Functions, Python).
2. Validator module (geometry, BFS reachability from stairway, budget,
   depth, trap caps) — pure functions, unit-test against hand-built
   good/bad quests BEFORE wiring the LLM.
3. (done) Baseline budget calibrated = 120; see Balance system.
4. Board renderer with fog of war + path input.
5. Zargon engine: movement (A* on revealed map), target selection,
   turn-type roller, combat prompts ("roll N defend dice, report shields").

## Working style (owner preferences)
- Direct, plain language. Bullets over prose. No performative filler.
- One command at a time during active execution; wait for results.
- State limitations before capabilities.
- Owner corrects course freely — when corrected, verify then apply.
