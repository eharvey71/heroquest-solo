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
(required so traps trigger mid-move and Zargon knows positions). TRACING
IS SETTLED -- click-to-destination with an auto-routed path, and
range-dots driven by a typed movement roll, were both weighed and
declined. Traps are the only reason the route is needed at all; revisit
after a real quest has been played, not before. A hero may trace THROUGH
a fellow hero: the tracing hook always allowed it, but BoardView's
pointer-down re-selected any hero whose square was tapped, so a teammate
in a corridor was a wall to a click-trace. Adjacency now decides -- while
a hero is selected, a tap next to the path's end is a step; a tap
further off switches heroes. Everything
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
  fog of war, tokens, path input, Zargon narration log. Layout (App.css
  + GameView): the board is sticky on the left, everything you press is
  in a rail on the right, and the rail is ordered by urgency -- things
  the app is WAITING on (defence rolls, a spell holding a hero, a trap
  underfoot) sit above things you may choose to do. Hero actions are a
  menu that expands one at a time, because the rulebook gives a hero
  one action per turn; showing six forms at once misrepresented that
  and buried the log below all of them. Path tracing state lives in
  GameView, not BoardView, so "Confirm move" sits in the rail next to
  the board instead of under it.
- State: Firestore. Collections: quests (validated definitions),
  games (runtime state). A quest never changes after generation, so the
  setup screen lists both: pick a past quest to start a fresh game on
  the same dungeon (fog, traps and monsters all reset), or resume a
  game in progress. Generating is not the only way in.
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
Tiles: stairs 2x2, blocked squares (8 single + 2 double = 12 squares,
and they do not recycle),
pit traps, falling block traps, secret doors, skulls. Spear traps
have NO tile ("there are no spear trap tiles") -- a sprung spear is
narrated and then gone forever.
When the app reveals anything with a physical tile (trap sprung, secret
door found, blocked square, stairs), it must show a "place tile"
instruction naming the tile and square(s).

Blocked squares are APP-owned, not model-owned. The printed quests fence
the play area in so the party can't wander the whole board; a generated
quest that populates 4 rooms out of 22 needs the same. The LLM is told
to declare none (it is bad at graph cuts, and this board's corridors are
a loop -- no single square ever seals a branch), and
functions/generator/fence.py computes the cordon after a quest
validates: skeleton (stairway + everything the quest uses + the shortest
paths joining them, never cut) -> sink (everything more than `d` steps
beyond it) -> minimum vertex cut between them, walking `d` out from 1
until the cut fits the 12 squares of tile. Typical result: 3-6 tiles cut
corridor roaming from 148 squares to 20-45. Corridor squares only, never
a door's own edge or a corridor trap. If no cut fits the tiles, there is
no fence -- an open board beats an instruction the owner can't follow.
A quest generated before the cordon existed gets one on the first game
started from it (create_game backfills and stores it).

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

## Simulator (functions/sim/)
A headless Monte Carlo playtester. Zargon's whole side is the SHIPPING
engine (movement, targeting, turn types, combat, traps, fog); the
heroes are a scripted model -- no equipment past starting weapons, no
potions, spells or treasure, and Body Points tracked by the sim since
they are physical in the app. So its ABSOLUTE win rates (91-96%) are
not a real party's and must never be quoted as one.

What it is for is differences: every cell of a sweep plays the same
seeds, so two rows differ by one rule. Method for pricing any rule
change: (1) sweep the budget multiplier to confirm the metric responds
-- currently ~1.4 Body Points per 10% of budget at 4 heroes; (2) run
the new rule at 1.0; (3) express the difference in budget-multiplier
terms. Body Points lost is the primary metric, not win rate, which
saturates for a healthy 4-hero party. `python -m sim.run --games 200`.
Findings are written up in sim/results/.

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

HERO SPELLS are built the same way as Zargon's (engine/hero_spells.py,
all twelve 1989 cards transcribed verbatim into data/hero_spells.json).
Cast INSTEAD of attacking, at a target the caster can SEE, once per
card per quest (spellsCast). WHICH cards a hero holds is chosen at game
creation: the Wizard takes three elements, the Elf one of what is left,
and no element is in two hands -- each element is one physical set of
three cards. Stored as game state's spellbooks; a hero can only cast
from their own elements, and the UI only offers those.

The split, card by card:
- App applies: Ball of Flame and Fire of Wrath (damage, less the
  MONSTER's own red-dice save -- Zargon's dice, so Zargon rolls them);
  Sleep and Tempest (monster statuses, below); the Genie both ways --
  opening any door on the board (seen or not) and attacking with its
  own 5 combat dice.
- App announces: Heal Body and Water of Healing (Body Points), Rock
  Skin and Courage (hero dice), Swift Wind (the doubled movement roll).
  Those are the player's sheet and the player's dice.
- App enforces as movement: Veil of Mist ("through spaces occupied by
  monsters") and Pass Through Rock ("through walls"). Both are
  one-move statuses the tracer and the engine honour, spent by the move
  that uses them. Pass Through Rock's "trapped forever in solid rock"
  has no equivalent here -- every square on this board is room or
  corridor, so there is nothing to be stranded in.

MONSTER STATUSES (engine/monster_status.py) are the mirror of
hero_status, and deliberately a separate module because the two sides
aren't symmetrical. A held HERO is stopped by refusing their actions
and breaks the spell with their own dice; a held MONSTER is stopped by
Zargon skipping its turn, and the app rolls its save (one red die per
Mind Point, a 6 wakes it) because monster Mind Points are digital.
Sleep also zeroes a monster's DEFEND dice -- "cannot move, attack, or
defend itself" -- which is what makes the card worth holding. Sleep may
not be used on mummies, zombies or skeletons.

HERO DEATH is reported, not deduced: Body Points are physical, so the
player presses "[hero] has fallen" and the app applies everything that
follows -- the figure leaves the board, so the square frees up, Zargon
stops pathing to it and stops asking for its defence rolls, it drops
out of cunning targeting, and standing on the stairway no longer ends
the quest. The roster entry STAYS (alive=False, never removed): party
size at game creation is what the quest budget was priced against and
what the lone-hero 2-actions rule keys off. A missing alive field means
alive, so games created before this still load. When the last hero
falls the status becomes "lost" -- the app's only end state other than
"complete" -- and a finished quest, won or lost, takes no further
actions (undo still works, so a misreported death is recoverable).

PENDING DEFENCE PROMPTS are GAME state (pendingDefenses), not client
state. When a monster attacks, the app names the skulls and waits for
the player's shield report; holding that queue in React meant it
outlived an UNDO of the very turn that raised it (a restore rewrites
the document, not the browser) and vanished on a refresh, quietly
costing the monster its hit. Zargon's turn writes the queue WHOLE, so
unanswered prompts can't leak into the next turn; a treasure-card
wandering monster APPENDS, since a prompt from Zargon's last turn may
still be open. Answering one removes it by id.

UNDO (engine/undo.py + main.undo_last_action) rolls the board back one
action at a time, all the way to the start of the game if need be.
Undo also clears the transient client state that belonged to the
rolled-back action -- a traced path, an open action form, a
rolled-but-unresolved Zargon turn.
Every mutating endpoint deep-copies the pre-action state and files it
under games/{id}/undo/{n} inside its OWN transaction, so an action that
raises leaves no snapshot and a snapshot never exists without its
action. Restores are whole-document writes, not merges: undoing has to
make things DISAPPEAR (a searched room, a spawned wandering monster, a
sprung trap, revealed corridor) and a field merge can only add or
overwrite. Each snapshot carries the label of the step beneath it, so
the button can name what it will undo without a second read.

ATTACK-THEN-MOVE is built (engine/turn.py WITHDRAW_POLICIES). The
rulebook lets a monster move then act, OR act then move -- never
move-partway-act-move, which is why only a monster that STARTED its
turn adjacent may use it. Three policies:
- "none": attack and stay put (the original behaviour).
- "reposition": may move but must stay adjacent to some hero. Measured
  at 1.2% of monster turns -- being flanked with an escape square is
  rare -- so it is nearly a no-op. Kept as an option, not the default.
- "fall_back" (DEFAULT): hit, then step to the NEAREST square out of
  every hero's reach. Fires on ~47% of monster turns. Not a sprint for
  the far wall: equally legal, looks absurd on the table, and measured
  no better.
A GUARD never withdraws whatever the policy says.

The old worry -- hit-and-run multiplies monster durability, threat cost
(attack+defend+body) has no term for it, so the calibrated 120 baseline
silently breaks -- was tested and did not hold. See the sim section
below: withdrawing trades damage output for survivability, because a
monster that leaves melee also spends the next turn walking back in.

CHAOS SPELLS are built (engine/chaos_spells.py, all twelve 1989 cards
transcribed verbatim into data/chaos_spells.json). The cards' own rule:
"give your Chaos spells to specific monsters called for in the Quest
notes", cast INSTEAD of attacking, only on a hero the caster can SEE,
once per quest each, then discarded. So spells are quest data
(monster.spells, validator-checked: NAMED monsters only, of a
spellcasting TYPE only, at most MAX_SPELL_CASTERS=2 of them in a quest
-- the quest book arms the villain and maybe a lieutenant, never the
rank and file -- and one physical card of each) and the app decides
when to spend them (chaos_spells.choose_spell -- room-wide cards wait
for a crowd). WHICH types may cast is data, not a constant: "caster":
true in data/monsters.json, read by validator.balance.caster_types and
fed to the generator prompt. The owner set it to the three figures
worth arming: chaos_warrior (4 owned), chaos_warlock (1), gargoyle (1).
A named orc is still an orc, and the shambling undead never cast.

chaos_warlock is not in the rulebook's eight-row monster table: the
figure stands in for named quest villains whose stats are printed in
that quest's own notes. Its catalog row is BALUR, the Fire Mage
(Quest 8) -- move 8 / attack 2 / defend 5 / body 3 / mind 7, threat
10. Frail in a swing and very hard to put to sleep, so his threat is
the Chaos cards he carries, not his sword. Balur is the lighter of the
book's two Warlocks; the Witch Lord (Quest 14) is move 10 / attack 5 /
defend 6 / body 4 / mind 6, threat 15 -- that gap is what the
named-monster `overrides` are for, so the catalog row is the floor,
not the ceiling.

The book's own Warlocks break the app's spell rules, and that is fine
-- not a gap to close. Balur carries six cards and the Witch Lord
five, against the two or three the generator prompt suggests, and the
Witch Lord casts Fear TWICE, which the validator's one-card-per-quest
rule reads as an error. Those are per-quest special rules the quest
book writes for one villain, the way it also declares Balur immune to
fire and the Witch Lord immune to everything but the Spirit Blade. A
generated quest gets the general rule: two or three cards, each once.
So chaosSpellsCast stays a set of spell ids, and no repeat-counting is
built.

The physical/digital line runs straight through the middle of the deck:
- The app applies what it owns: damage to MONSTERS, summons (capped by
  free minis, proxy suggested otherwise), the Escape teleport, and the
  status a spell leaves on a hero.
- It announces what it doesn't: hero Body Points, the "roll two red
  dice, each 5-6 saves a point" reductions, Rust's ruined weapon, and
  every Mind Point break roll. Those are the player's dice and the
  player's sheet, same handoff as skulls and shields.

Five cards leave a STATUS (engine/hero_status.py): asleep, paralyzed
(Cloud of Chaos), commanded, becalmed (Tempest) all stop a hero acting
-- enforced at every hero endpoint via heroes.require_hero_can_act --
and afraid only costs attack dice, so it is shown, never enforced
(hero dice are physical). Breaking one is the hero's own roll reported
through attempt_break_spell; Tempest can't be broken, it just expires
when the missed turn passes.

Not implemented, deliberately:
- Command moves a hero on Zargon's turn. The app marks the hero as
  commanded and hands Zargon the figure, but does not path or attack
  with it: hero movement is 2d6 physical and hero attack dice depend on
  equipment the app cannot see. The player moves the commanded hero as
  Zargon directs.

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

## Open items
The original first tasks are all done and deployed: Firebase skeleton,
validator, baseline budget (120), board renderer with fog + path input,
and the Zargon engine (movement, targeting, turn-type roller, combat
prompts).

Hero death and undo are built (see the engine details above).

Auth is locked to one account (see below), and chest/furniture traps
are built (see the engine details above).

Chaos spells and hero spells are both built and priced (see the engine
details above). All twelve cards of each deck are transcribed, the
three caster types are flagged in monsters.json, and the quest schema
carries monster.spells.

Known gaps:
1. Command moves a hero on Zargon's turn -- deliberately left to the
   player, see "Not implemented, deliberately" above.
2. The app has never been played through a full quest on the physical
   board. Everything below is verified by tests and the simulator,
   which is not the same thing.

## Single-owner auth (settled)
Google sign-in, and the app belongs to exactly ONE account. The uid is
NOT hard-coded: it lives in the config/owner document, written once by
the first account to sign in (web/src/lib/firebase.ts claims it), and
made immutable by firestore.rules -- create only, never update or
delete. A rules file with a pasted uid was rejected as the fix: one bad
string in a deploy and the owner is locked out of their own dungeon,
with no way in through the app.

Three enforcement points, because each covers a hole the others don't:
- firestore.rules: direct client reads/writes of quests, games and undo
  snapshots require request.auth.uid == the claimed uid.
- functions/owner.py + main._require_owner: Cloud Functions use the
  Admin SDK and BYPASS the rules entirely, so every callable repeats
  the check itself. Before the claim exists it falls back to "any
  signed-in user" -- the pre-lock behaviour -- so a fresh deploy is
  usable in the seconds between deploying and signing in once.
- The client proves ownership by CAPABILITY, not by comparing uids:
  config/owner is readable only by the owner, so a successful read is
  the proof. There is no string the client can lie about.

## Working style (owner preferences)
- Direct, plain language. Bullets over prose. No performative filler.
- One command at a time during active execution; wait for results.
- State limitations before capabilities.
- Owner corrects course freely — when corrected, verify then apply.
