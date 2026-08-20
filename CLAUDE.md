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
at game creation: quest data marking a door "open" only means "not
secret" -- it is not a claim the door stands open on turn 1, and
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
nothing physical: only "secret" (must be searched for) carries
meaning. There is NO locked-door state -- it came from the v0.1 schema,
not the rulebook, which has no lock mechanic and no locked-door piece;
the app had no way to grant a key, and the validator counted locked
doors as passable, so a quest could be certified reachable through a
door nothing could ever open. Removed; legacy quests read a stored
"locked" as closed. No simultaneity cap is needed and none
should be built: the owner confirms more than 5 doors are never closed
on the board at once in real play, so the app does not track closed-
piece supply or emit "place a closed door" instructions.
Tiles: stairs 2x2, blocked squares,
pit traps, falling block traps, secret doors, skulls. Spear traps
have NO tile ("there are no spear trap tiles") -- a sprung spear is
narrated and then gone forever.
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

Line of sight ("SEE", 1989 rulebook page 15, verified against the
owner's photos): a target is visible if a straight line between square
CENTRES crosses no wall, closed door, hero or monster -- corner grazes
count as visible, but only where sight could actually pass (allowing
every diagonal let a line escape a sealed room between two wall
corners). engine/line_of_sight.py.

Two callers, deliberately different blocker sets:
- TARGETING (visible monsters; later, spell targets) applies it
  strictly -- figures block.
- REVEALING (corridor fog) ignores figures, so terrain once seen stays
  seen; a hero sidestepping must never un-reveal a corridor. Walls and
  closed doors still block, so the party never sees round a corner.
Corridor fog now lifts by SIGHT from every square walked, not one
square at a time. ROOM fog stays door-gated -- the rulebook reveals a
room's contents when its door is OPENED, not by peering in.

Adjacency and attacks: all engine geometry is ORTHOGONAL only
(engine/movement.py `_STEPS`) — no diagonal movement or attacks.
Monsters may only attack a hero orthogonally adjacent to them, and
engine/turn.py enforces it (a monster that can't reach adjacency logs
"isn't in range yet" and does not attack). Hero attacks are the
deliberate exception: the app cannot see hero weapons (physical), and
a spear attacks diagonally while a crossbow attacks at range, so a
non-adjacent target is WARNED about ("diagonal — spear only", "not
adjacent — crossbow or spell only") and never blocked. Enforcing hero
adjacency was rejected for exactly this reason.

Searching (1989 rulebook, Actions 3-5, verified against the owner's
photos): SEARCH FOR TRAPS and SEARCH FOR SECRET DOORS are two DISTINCT
hero actions, not one button -- a hero takes one action per turn, so
combining them handed the party a free action. searchType picks one;
each has its own once-per-room flag (searched.<room>.traps /
.secretDoors). Treasure may only be searched in a room UNINHABITED by
monsters; traps and secret doors only when no monsters are visible
(approximated as "none in the hero's room" until line of sight is
modelled). A FOUND trap gets no tile -- "Zargon will NOT put any trap
tiles out on the board; they are still concealed and unsprung" -- the
tile goes down only when it is sprung. A found secret door DOES get a
secret-door tile, and still needs the open-door button afterwards.
Blocked squares stop monsters as well as heroes.

Traps (1989 rulebook, verified): springing one ENDS the hero's
movement -- every trap description finishes "This ends your turn". The
two types the generator emits differ in where the hero lands: a PIT
swallows them, so they end ON the trap square with the tile under the
figure; a FALLING BLOCK brings the ceiling down before they are
through, so they never take the square and stay put (the rulebook
offers forward or back; the app can't prompt mid-move and picks back,
which can't strand them). A sprung falling block becomes a PERMANENT
block for heroes and monsters alike -- tracked as game state's
collapsedSquares, since quest data can't know it. FOUND and SPRUNG are separate registries: trapsFound (known, still
ARMED -- stored as {trapId: {type,pos}} so the client can offer
jump/disarm without being handed the quest's hidden trap layout) vs
trapsTriggered (sprung or disarmed, permanently inert). Conflating
them let a search disarm a whole room for free. Movement STOPS in
front of a known trap ("known_trap"), same two-step shape as a door,
and the hero picks JUMP, DISARM, or step on it deliberately
(engine/trap_action.py). The die is the hero's: the app names the roll
and the player reports the face. Dwarf disarms bare-handed and fails
only on a black shield; anyone else needs a tool kit (physical, so the
caller asserts it) and fails on a skull.

Sharing a square is allowed in exactly the rulebook's two cases: the
stairway footprint, and a SPRUNG pit (an unsprung one is still covered
floor). A monster standing in a sprung pit attacks with one die fewer,
minimum one -- the rulebook's pit penalty explicitly applies to
monsters too.

Monsters may not (1989 rulebook, Zargon's Turn page, verified against
the owner's photos): search for treasure or secret doors, move or
attack diagonally, pass over heroes, move through walls, OPEN OR CLOSE
DOORS, or share a square. All are enforced. The door one is easy to
get wrong: monsters path only through doors the HEROES have opened --
closed and secret are walls to Zargon (engine/movement.py
passable_door_edges). Monsters also never spring traps, and need not
spend their full movement allowance.

Hero spells (1989 rulebook, Action 2 -- engine/spell.py): the Elf and
Wizard only, cast INSTEAD of attacking, at any target they can SEE
(the real line-of-sight rule), once per spell per quest
(game state's spellsCast). Spell CARDS stay physical -- the app has no
spell catalogue and never learns what a card does. The player names
the card; for an attack spell they report the skulls it rolled and the
engine applies damage exactly as for a weapon attack, with a
monsterDefends flag for cards that allow no defence roll. A spell
aimed at a hero (healing, buffs) touches only physical state, so the
app logs it, spends the card, and changes nothing else.

Not implemented, deliberately:
- Attack-then-move. The rulebook lets a monster act then move (not
  move-partway-act-move); the engine only does move-then-attack, so
  Zargon never hits and withdraws. Tried and reverted: making adjacent
  monsters attack-then-withdraw is legal by the rules but turns every
  melee into hit-and-run, which raises effective monster durability a
  long way. Threat cost (attack+defend+body) has no term for that, so
  it invalidates the calibrated 120 baseline exactly as chaos spells
  would. Build it only alongside a re-run of the sim.
- Chaos spells. Monsters can attack and nothing else; monsters.json
  carries no spell data and no catalog monster is a caster. The
  rulebook does permit spells in custom quests (cast INSTEAD of
  attacking, only on a hero the caster can see, once per quest each),
  so this is a real feature if wanted -- the cost is that threat cost
  (attack+defend+body) has no term for spell value, so adding casters
  invalidates the calibrated 120 baseline until the sim is re-run.

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

Ending a quest takes TWO stages (1989 rulebook, Hero Movement: "To
safely complete a Quest, you must return to the stairway, for it is
only there that you are truly free from harm"). Stage 1: the objective
is met -> game state's objectiveComplete, and the log tells the party
to head back. Stage 2: a hero reaches the stairway footprint ->
status "complete" and completionText. Firing on the objective alone
skipped the walk home entirely.

WHO must get back is deliberately "any hero": hero death is physical,
so the app can never know who survived and "all survivors" is not
computable. Revisit only if hero death ever becomes digital.

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
