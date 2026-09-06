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
treasure deck; the app only needs to know if a wandering monster is
drawn, and it asks AFTER the draw, not before: pressing Search ->
Treasure rules the search legal and un-trapped, tells the player to
draw ONE card, and leaves pendingTreasureDraw on the game;
resolve_treasure_draw answers "was it the wandering monster?" (a
checkbox asked BEFORE the search was tried and scrapped -- the player
can't know yet, and a chest trap can mean no card is drawn at all).
While the answer is owed, every other action and End Turn are blocked,
client and server both -- same pattern, same guard
(_require_no_pending_defenses) as the defence queue. One treasure
search per HERO per room (owner verified against the 1989 rulebook;
an earlier "once per room total" reading was wrong), app enforces via
searched.<room>.treasureBy.

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
  TOKENS WALK THEIR ROUTE (Tokens.tsx): a hero or monster that moved
  steps square by square along the squares it actually crossed, four
  directions only, turning the corridor's corners the way the mini
  does on the table. The route is GAME state, game.lastMoves
  ({figureId: [squares, start first]}), written whole by every
  endpoint that moves a figure -- resolve_movement (the path walked,
  cut short where the move stopped), resolve_trap_action (onto the
  trap, and past it on a cleared jump), resolve_zargon_turn (each
  monster's approach or fall-back, from engine/turn.py's
  MonsterTurnResult.path). Game state rather than a response field so
  the route and the new position arrive in ONE Firestore snapshot --
  the callable's response and the listener's snapshot race, and a
  path that arrives after the token has already started sliding is
  useless. The client walks a route only if it starts on the square
  the token is drawn on and ends on the figure's new square, so a
  stale entry (the field is left alone by endpoints that move
  nothing) can never send a token the wrong way; it keeps the
  previous document's routes for one comparison so an UNDO retraces
  the last move backwards. No matching route (undo further back,
  Escape's teleport, a game opened mid-play) means a straight slide,
  or -- for a figure just revealed, spawned, or loaded -- no motion at
  all. Driven per frame in JS (requestAnimationFrame), not a CSS
  transition, which can only tween a straight line; the reduced-
  motion preference skips it. Verified in headless Chromium with a
  Playwright harness (corner turned, undo retraced, stale route
  ignored) -- the rAF timestamp can precede the walk's own start
  stamp, which indexed the path at -1 until clamped.
  HEADER ROW: Story, Chronicle, Undo and the game id live in App's
  header beside "Back to quests & games" and Sign out -- one row for
  everything that isn't a game action. They used to share a row with
  the turn heading above the rail, where they crowded and sometimes
  collided with rail panels. GameView renders them through a React
  portal into a slot element App passes down (toolsSlot) -- their
  state is GameView's, and the slot is passed as an element rather
  than looked up by id so it exists by the time GameView renders.
  LEGEND COLOURS come from the constants BoardTerrain draws with
  (exported DOOR_COLORS / STAIRWAY_STROKE), not copies -- they had
  drifted. Closed door is dark red, stairway dark purple, armed-trap
  marker amber: the owner couldn't tell three ambers apart.
- State: Firestore. Collections: quests (validated definitions),
  games (runtime state). A quest never changes after generation, so the
  setup screen lists both: pick a past quest to start a fresh game on
  the same dungeon (fog, traps and monsters all reset), or resume a
  game in progress. Generating is not the only way in. The setup
  screen's list is QUEST-GROUPED, not two flat lists side by side --
  each quest's games nest under it, since a quest is one immutable map
  and its games are however many times it's been played. Each game
  shows both "started" (createdAt) and "last played" (lastActionAt,
  bumped by main._push_undo -- the one choke point nearly every
  mutating endpoint already passes through right before its write --
  and by undo itself, stamped fresh rather than rolled back to the
  snapshot's old value, since undoing is an action happening now).
  Removing a quest or a game from the list ARCHIVES it (an `archived`
  flag, lib/archive.ts) rather than deleting -- "remove the entire
  stack" on a quest cascades to every game played on it, found by a
  live questId query rather than just whatever page the list already
  had loaded, so a quest with many replays still archives completely.
  A "Show removed" toggle brings archived rows back with a Restore
  button. Direct Firestore writes, not a Cloud Function: firestore.rules
  already lets the owner write quests/games directly (the same
  boundary config/owner's claim-by-write already uses), and flipping a
  visibility flag has no business logic to hide behind the Admin SDK.
- Backend: Python Cloud Functions.
  - generateQuest(params) -> questId: prompt build + LLM call + validate +
    auto-repair + retry loop (max 3) + Firestore write. Client never sees
    an unvalidated quest.
  - generateChronicle(gameId) -> chronicle: one LLM call, no retry loop
    (prose has no hard constraint to fail the way a quest's reachability
    or budget can), turning a FINISHED game's mechanical turn log into a
    page of read-aloud prose -- the campaign record of that playthrough.
    Callable only once game.status is "complete" or "lost"
    (generator/chronicle.py). Fired automatically by the client the
    moment a game ends, not on a button press -- there's no gameplay
    reason to make the player ask for it. Not transactional and pushes
    no undo snapshot: it writes one derived text field onto a game
    nothing else can still be mutating, with nothing gameplay-
    consequential to roll back.
  - generateQuest's optional continuesFromGameId links a new quest to a
    finished, chronicled one as its sequel -- CAMPAIGN CONTINUITY.
    main._resolve_campaign_context requires the named game to be
    complete/lost AND already chronicled (a quest can't continue from a
    story that hasn't been written yet), then hands the chronicle text
    into the prompt (generator/prompt.py's _campaign_section). The
    model MAY thread it into the new backstory -- a villain who
    escaped, an artifact recovered, a hero remembered -- but every
    quest must still stand completely on its own; a player who never
    read the chronicle needs nothing else to play it. The pointer is
    stored on the new quest doc (continuesFromGameId) as provenance,
    not re-validated -- continuity is narrative, so nothing here
    constrains quest STRUCTURE the way artifacts or balance do. Setup
    screen: a "Continue from" picker lists chronicled games only.
  - generateTurnNarration(gameId, turn) -> narration: TURN NARRATION,
    the live counterpart to the chronicle -- one short flavor paragraph
    (2-4 sentences) per turn, colouring that turn's own mechanical log
    lines, not summarising the whole game (generator/narration.py).
    Idempotent and cheap to call again: writes game.narration[turn]
    (a map keyed by turn number, since narration for turn 5 can arrive
    after turn 6's mechanical lines are already logged -- a flat
    array would have no stable place to insert it) and a call for an
    already-narrated turn returns the cached text without touching the
    LLM. Client fires it (GameView.tsx) the moment a turn closes --
    when game.turn advances past it, or, for the final turn, the
    moment status becomes complete/lost (that turn never gets a
    Zargon-turn boundary to close it the normal way). Deliberately NOT
    backfilled for a game's whole history on load: the trigger seeds
    its "already seen" turn to whatever the CURRENT turn is on first
    render and only narrates turns that close after that, so opening
    an old finished game narrates just its one final turn, not one LLM
    call per turn ever played. Same non-transactional, no-undo-
    snapshot reasoning as the chronicle. Rendered as its own "The
    story so far..." panel directly above the Log (GameView.tsx) --
    the paragraphs accumulate in turn order and read as one running
    tale, auto-scrolled to the newest. Splicing them between log lines
    was tried first and read badly: prose interrupting a monospace
    record. The log stays purely mechanical (and shorter for it).
    Narration and the chronicle both build their prompt from the same
    log lines, and both hit the same bug: those lines carry the app's
    own bookkeeping labels (room ids like R16, square coordinates,
    trap/monster ids) meant for a player reading the log directly, and
    the LLM faithfully echoed them into read-aloud prose ("beyond the
    opened door in R16") -- meaningless at a physical table with no
    room numbers printed on it. Both prompts now forbid printing a raw
    id or coordinate outright and require narrative language instead
    ("the room beyond", "a deeper chamber").
  - Zargon rules engine: deterministic code (movement, target choice,
    combat resolution). LLM is NEVER in the rules path — only quest
    generation and flavor narration (the chronicle, campaign
    continuity, turn narration).

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

An OPEN (sprung) pit is the one trap that stays interactive (rulebook
p.19-20, verified against design/heroquest-rulebook-1989.pdf): a hero
crossing it must JUMP (anything but a skull clears it; a skull drops
them in for 1 Body Point) or climb in deliberately (also 1 Body
Point), and it can never be disarmed. Movement stops at the pit's
edge ("open_pit", same two-step shape as known_trap) and the client's
open-pit panel resolves the choice with one-click die buttons. That
panel is shown only for the pit a traced move JUST stopped at
(GameView's trapStop, set from resolve_movement's stoppedAtTrapId and
cleared by the trap action, undo, or end turn) -- adjacency alone kept
it up after a successful jump, since the hero lands next to the hole.
WHERE a jump lands (any trap, armed or open) is the rulebook's p.20
rule, not "straight across": "as many as 3 possible squares to jump
to on the other sides of a single pit ... a pit in the corner of a
corridor has only 1". Any side of the trap the hero isn't on counts,
provided the hero could have STEPPED there from the trap square --
same area or an OPEN door edge, not blocked/collapsed, not furniture,
not occupied. engine/trap_action._landing_problem enforces it (found
in live play: a straight-across jump put a hero through a room wall,
and the server let it), and the client offers only legal sides, pre-
selecting the square the traced path was heading to past the trap.
Climbing OUT is ordinary movement -- only entering costs. Monsters
clear open pits automatically (the book says they always make the
jump), so monster pathing treats them as passable, and the sim's
scripted heroes auto-jump so they can't wedge behind their own pit.
Every other sprung trap is inert: spears are gone forever, falling
blocks become collapsedSquares.

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

heroStatus is not one uniform thing, and a real bug came from treating
it as one: Chaos afflictions (asleep, paralyzed, commanded, becalmed,
afraid) and a hero's own one-move spell BOONS (veiled, through_rock)
share the same registry but mean opposite things. The client's Chaos
alert -- purple, with Mind Point break-roll buttons -- was firing on a
hero's OWN Veil of Mist, offering to "break" a spell the hero had just
cast on themselves. The server was never fooled (attempt_break_spell
only ever touches the affliction list), but the panel now splits
heroStatus into afflictions vs. boons and shows a boon in its own
quiet "Spell active" panel instead.

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
still be open. Answering one removes it by id. Ending the hero phase
is BLOCKED while any prompt is still open (engine/end_turn.py's
DefencesPendingError) -- a stray click on End Turn used to reach
Zargon's phase with a shield report still outstanding, and the next
resolve_zargon_turn's whole-queue write silently discarded that hit
for good.

The whole action panel, not just End Turn, is gated on the same
condition, both sides: resolving Zargon's turn flips phase back to
"hero" in the same response that creates the prompts, so the ordinary
hero actions (Attack, Search, Open door, Cast spell, the known-trap
Jump/Disarm/Step panel, confirming a traced move) were sitting there
clickable next to an unresolved "N skulls" prompt -- physically you'd
defend the hit before doing anything else. Client-side, each of those
panels checks pendingDefenses is empty before rendering its buttons.
Server-side, main._require_no_pending_defenses (called by every one of
those endpoints, right after _require_playable) rejects the call
outright, so a stale tab or a direct API call can't bypass the hidden
buttons -- deliberately NOT called by record_hero_defense (clears the
queue), record_hero_death (a hero can die from the very hit that's
pending), attempt_break_spell (not "the one action"), undo (the escape
hatch), or resolve_zargon_turn (can only run in Zargon's phase, which
end_turn already refuses to reach with anything open).

Each pendingDefenses entry also stamps the TURN the attack happened
(a real bug, found in live play): resolve_zargon_turn advances
game.turn in the same write that queues the prompts, so logging a
defence roll under "now" filed its log line under the NEXT turn's
header -- reading as the start of the hero phase instead of the end
of Zargon's. record_hero_defense now splices the line in at the end
of the attack's own turn (right after "Zargon ends his turn", before
the next turn's "--- Turn N ---" marker), and the client holds turn
narration until pendingDefenses is empty -- narrating before the
block was reported had the narrator call every swing a wound, since
it never saw the "0 wound(s)" line saying otherwise.

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

ARTIFACTS (data/artifacts.json, all ten 1989 cards transcribed
verbatim) are PLACEMENT only so far -- none of their ten effects are
enforced. Never awarded by a random treasure search: the app never
sees what a hero draws from that deck (same boundary as gold and Hero
spell cards), so an artifact can only enter a quest if the generator
places it deliberately, validator-checked, one of two ways: as the
`find_artifact` objective's actual goal (objective.target.artifactId),
or as loot tucked in one room's furniture along the way
(furniture.contains.artifactId) -- either, both, or neither, and never
the same artifact placed twice (there is one physical card of each,
validator/artifacts.py). Naming the artifact doesn't change how the
objective completes -- still "a hero reached target.room"
(engine/objective.py, unchanged) -- it just lets the LLM's own prose
(which already writes backstory/completionText/revealText for every
quest) reference the real name and effect instead of staying generic.
The catalog degrades to a no-op if ever emptied: both schema
properties and the prompt's whole ARTIFACTS section are generated FROM
it and omitted entirely when it's empty.

Four of the ten touch state the app already tracks and are real
candidates for future digital enforcement: Ring of Return (teleports
hero tokens to the stairway -- positions are digital), Spell Ring and
Wand of Magic (both bend the "one spell, once per quest" rule
hero_spells.py already enforces via spellsCast), Elixir of Life
(revives a hero -- alive/dead is digital per engine/heroes.py, Body
and Mind Points are not). The other six are hero combat-dice bonuses
and restrictions -- physical-only, same boundary as any other weapon
or armor card. See data/README.md for the full breakdown.

Two distinct wandering-monster mechanics, different placement rules —
do not conflate them:
- **Treasure-card wandering** (drawn during a physical treasure
  search, reported via resolve_treasure_draw): rulebook-mandated, not a
  design choice. Appears ADJACENT to the searching hero, IN THE
  SEARCHER'S OWN ROOM, and attacks immediately. In-room matters: an
  adjacent square across a wall belongs to the next room, which is
  unrevealed, so the figure lands in fog the token layer can't draw --
  invisible and unreachable (a Wizard searching R15 spawned an orc one
  square north in R12). The rulebook already says so: "put the monster
  in the room as close to the searcher as possible." Nearest free
  square WITHIN THE ROOM if every adjacent square is occupied.
- **Turn-roll wandering** (the Zargon Deck's `wandering` turn type,
  no searcher involved): spawns at the nearest unrevealed
  doorway/corridor edge to the party (the "frontier"). Stairway is
  the fallback ONLY when no frontier exists yet (e.g. turn 1) —
  spawning at the stairway by default was tried and rejected: late in
  a quest it lands far behind cleared territory and spends several
  turns just walking back to relevance.

Both wandering cases emit a "place the [type] mini at square [x,y]"
instruction, same convention as trap/secret-door reveals.

Those placement instructions are GAME state (placementInstructions), a
queue the app appends to whenever it reveals something with a physical
tile or mini -- a sprung trap, a found secret door, an opened room, a
spawned monster, a Chaos summon. Every engine already produced the
line and every one went ONLY to the log, at the bottom of the rail:
the player took a wandering monster's attack out of nowhere with no
idea what figure to stand on the board. Now they surface in their own
"Place on the board" alert at the top of the rail, and a defence
prompt names its attacker and the square it stands on, so "3 skulls"
is never faceless. Game state rather than a response field, for the
same reasons the defence queue is: undo takes them back, a refresh
keeps them. Cleared when the hero phase ends -- anything unplaced then
belonged to a turn that is over.

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
Everything through the three AI features (post-quest chronicle,
campaign continuity, live turn narration), the ten Artifact Cards
(placement-only), and the Quests & Games list redesign (quest-grouped,
last-played dates, archive-not-delete) is built -- see Architecture
and the engine details above for each; this section only tracks what
is genuinely still open, so it doesn't re-list what's already settled
and risk drifting out of sync with it.

Known gaps:
1. Command moves a hero on Zargon's turn -- deliberately left to the
   player, see "Not implemented, deliberately" above.
2. Real play has started (traps sprung in a corridor, treasure drawn,
   spells cast) and has already surfaced and fixed several bugs tests
   and the simulator missed -- the treasure-draw ordering, open pits,
   spear-trap die reporting, Veil of Mist's status mix-up, defence
   rolls filing under the wrong turn. No quest has yet been played
   start-to-finish to a confirmed win or loss, so treat anything not
   yet exercised at the table as simulator-verified only, not
   table-verified.

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

## Firestore is only ever touched from the deployed functions (settled)
Nothing in this repo opens a Firestore client on the owner's machine:
main.py's initialize_app()/firestore.client() run only inside Cloud
Functions (where the runtime supplies the project), the web client
hard-codes projectId hq-zargon-solo, tests use fake transactions, and
the simulator and tools/repro_grammar.py never import firestore. Keep
it that way. The owner's machine has gcloud's machine-global default
project set to a DIFFERENT project, and Admin-SDK credentials bypass
security rules -- so any local script that called initialize_app() or
firestore.Client() without an explicit project would write this app's
games/quests into that other project's database, silently. If a local
Admin-SDK script is ever genuinely needed, it must take its project id
from .firebaserc (the repo's own `firebase use` alias) and pass it
explicitly; never rely on the ambient default, and never tell the
owner to run an ad-hoc firebase_admin / `gcloud firestore` one-liner.

## Working style (owner preferences)
- Direct, plain language. Bullets over prose. No performative filler.
- One command at a time during active execution; wait for results.
- State limitations before capabilities.
- Owner corrects course freely — when corrected, verify then apply.
