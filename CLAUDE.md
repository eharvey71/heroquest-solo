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
monsters.json). Heroes may pass through fellow heroes -- and nothing
else. Monsters and furniture are both impassable (furniture is a solid
obstruction on the physical board; furniture squares are also removed
from the validator's reachability BFS, so a piece can't seal a room the
validator thinks is reachable). Heroes may not end on an occupied
square. Doors are opened FROM the doorway: a hero stops at a door,
tells Zargon, and the room is revealed without stepping inside --
entering first would mean walking onto whatever stands behind it. The
app derives openable doors from where the hero stands, so no walk-into
attempt is needed to discover a closed door. EVERY door starts closed
at game creation: quest data marking a door "open" only means "no lock,
no secret" -- it is not a claim the door stands open on turn 1, and
taking it literally let heroes walk straight into unrevealed rooms.
Opening a door REPLACES the closed piece with an open one (see the
component notes below). Treasure searches use the physical
treasure deck; the app only needs to know if a wandering monster is drawn
(button for it). One treasure search per HERO per room (owner verified
against the 1989 rulebook; an earlier "once per room total" reading was
wrong), app enforces via searched.<room>.treasureBy.

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
Doors: 21 pieces (16 open, 5 closed) -- that is an inventory of
PIECES, not a cap on closed doors. Every door is placed closed; when a
hero opens one, Zargon REPLACES the closed piece with an open piece,
freeing the closed piece for reuse. So closed pieces recycle, open
pieces accumulate. Quest-declared door state therefore constrains
nothing physical: only "locked" (needs key/spell) and "secret" (must be
searched for) carry meaning, and locked is capped at 5 as a difficulty
knob, not a component count.
Tiles: stairs 2x2, blocked squares,
pit traps, falling block traps, secret doors, skulls.
When the app reveals anything with a physical tile (trap sprung, secret
door found, blocked square, stairs), it must show a "place tile"
instruction naming the tile and square(s).

## Balance system (from prior Monte Carlo sim work — "Zargon Deck")
Monster threat cost ≈ attack + defend + body. Budget by heroCount:
4 heroes 100% of baseline, 3 -> 85%, 2 -> 70% (+1 healing potion each),
1 -> 55% (+lone hero takes 2 actions/turn — enforced, see engine details).
Zargon turn types rolled per turn (replaces physical card deck):
4H: 72/24/4 normal/cunning/wandering. 3H: 76/20/4. 2H: 80/16/4. 1H: 84/12/4.
Cunning turn = focus-fire lowest-threat-to-kill hero, guard objectives.
Sim-tested win rates 79-92% at these ratios (combat + pacing only).
BASELINE CALIBRATED from 4 official quests (owner's maps, icon counts):
The Trial ~119, Rescue of Sir Ragnar ~104, The Fire Mage ~148,
[3rd color map, undead+goblins] ~117. Baseline (4-hero) = 120.
Targets: 4H 120 / 3H 102 / 2H 84 / 1H 66, all +/-10%; hard +15%.
Named bosses (Verag, Balur, Gulthor...) priced as base type + override cost.

## Zargon engine details (settled — see functions/engine/)
Combat die (confirmed against the owner's physical die): 6 faces = 3
skull, 2 white shield, 1 black shield. Skull = hit for whichever side
is attacking. Shields are NOT interchangeable: white shield only
blocks for a defending HERO, black shield only blocks for a defending
MONSTER — this is why monster defend stats lean on higher dice counts
rather than good per-die odds (1-in-6 vs a hero's 2-in-6).

Lone-hero 2-actions rule: an "action" = one FULL move+action cycle
(a complete hero turn), NOT one button press. Enforced as two hero
phases per game turn: game state carries heroPhaseSegment (1|2);
end_turn on segment 1 stays in the hero phase and advances to
segment 2, on segment 2 hands off to Zargon. UI shows "action N of 2"
and relabels the end-turn button. Per-press action counting was
rejected — the app doesn't police turn structure inside the hero
phase for 2-4 hero parties either (the table does), and the hero
rolls fresh movement dice each cycle exactly as a second hero would.
Lone-hero status = roster size at game creation (what the quest
budget was priced against), not survivor count — a 4-hero party down
to one survivor does not start double-acting.

Guard objectives (cunning turn): a monster stationed in the
objective's own room holds position rather than chasing. Trigger to
engage is hero IN the guard's room, OR standing at an open doorway
into it (can see in without having stepped inside) — NOT mere grid
adjacency to the monster's own square. ("Holds until adjacent" was
tried and rejected: it let a hero walk in, search the room, and loot
around a guard that never woke up.) Plain grid adjacency across a wall
with no door there does not count as a sightline.

Cunning-turn targeting ("focus-fire lowest-threat-to-kill hero") needs
hero BP, which is physical-only (see boundary above). Resolved as a
one-time prompt: when a cunning turn rolls and more than one hero is
in play, the app asks "which hero is lowest on BP?" and uses the
answer for that turn only — never stored as ongoing state.

Two distinct wandering-monster mechanics, different placement rules —
do not conflate them:
- **Treasure-card wandering** (drawn during a physical treasure
  search, the "wandering monster?" button): rulebook-mandated, not a
  design choice. Appears ADJACENT to the searching hero and attacks
  immediately. Nearest free square if every adjacent square is
  occupied.
- **Turn-roll wandering** (the Zargon Deck's `wandering` turn type,
  no searcher involved): spawns at the nearest unrevealed
  doorway/corridor edge to the party (the "frontier"). Stairway is
  the fallback ONLY when no frontier exists yet (e.g. turn 1) —
  spawning at the stairway by default was tried and rejected: late in
  a quest it lands far behind cleared territory and spends several
  turns just walking back to relevance.

Both wandering cases emit a "place the [type] mini at square [x,y]"
instruction, same convention as trap/secret-door reveals.

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
