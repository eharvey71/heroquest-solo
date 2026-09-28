# Side Quests — Design v0.1

Short narrative scenes, written together with the main quest, that the
party plays inside the app in 10-15 minutes. They strengthen the party
(an item, a boon, a weakened villain) or, sometimes, are the key the
finale needs. The board stays where it is; the story leaves it for a
while and comes back.

Owner's brief (Sept 2026): "1-2 optional side quests with the
possibility of a random 3rd required quest ... to get an item to
strengthen the party or complete a goal before they can defeat a final
boss or a horde ... return to a town, forest, cave, or whatever makes
sense ... same path as now in terms of dice rolls and Zargon
controlling things ... if a town is a side quest, remind the party the
Armory is available."

---

## 0. Two ways to play: traditional and expanded (owner's call)

Side quests are a VARIANT the players choose, never the default they
have to opt out of.

- **Traditional**: exactly today's game. No side quests, no gate, no
  Journal. Nothing about it changes.
- **Expanded**: everything in this document.

The choice is made where side quests are made: on the setup screen
when generating a quest ("Traditional" / "Expanded: side quests"),
default Traditional. It is stored on the quest (`mode`), because the
required gate is woven into the backstory and cannot be bolted on
later. Starting a game on an expanded quest offers the same choice
again, so a replay can go traditional: the game stores `mode` too, and
a traditional game on an expanded quest starts with the gate open and
the Journal hidden. A traditional quest can only be played
traditionally (there is nothing to expand).

## 1. Constraints this design inherits (CLAUDE.md, settled)

- The LLM writes prose and structure; it never decides an outcome.
  Every choice resolves to an effect from a closed list the engine
  applies, validated before the quest is saved. Same contract as quest
  generation: the client never sees an unvalidated side quest.
- Physical/digital boundary unchanged. Hero dice are rolled at the
  table and reported; Zargon's dice are rolled by the app. Body Points,
  gold, inventory and the treasure/equipment decks are never entered.
  Rewards that touch them are ANNOUNCED, same handoff as Heal Body.
- Quests are immutable after generation. Side quests are generated
  WITH the quest and stored on the quest document. Party composition
  (which heroes) is chosen at game creation, so hero-specific content
  is tagged and filtered at play, never baked in.
- No locked doors. A required side quest gates the OBJECTIVE, never a
  door (section 7).
- Prose rules already in force for narration and the chronicle apply:
  no room ids, coordinates or trap/monster ids in read-aloud text.

## 2. Kinds and counts

| kind | per quest | purpose | if failed |
|---|---|---|---|
| optional | 1-2 | strengthen the party, deepen the story | no reward, small sting, quest unaffected |
| required | 0-1, rolled at generation (1 in 3) | the key the finale needs: break the boss's ward, unseal the vault | finale becomes HARDER, never impossible (section 8) |

The server rolls the required-quest coin BEFORE the main quest prompt
is built, so the main backstory and objective text can plant it ("the
Warlock cannot be harmed while the Black Candle burns"). Randomness is
the server's, never the model's.

## 3. Where a side quest happens

- On its own page. The board is hidden; the rail is replaced by the
  scene. The main game is LOCKED while a scene is in progress, exactly
  the way a pending treasure draw locks it today: `pendingSideQuest` on
  the game doc, refused by `_require_no_pending_defenses`' guard on the
  server and hidden buttons on the client.
- In the fiction the party goes wherever the scene says: the town
  above, a forest glade, a cave beneath the crypt, a shrine, the road
  in, a vision. On the board nothing moves. The scene's last passage
  brings them back to the square they left. Settings are a prompt-side
  list the generator chooses from to fit the backstory.
- A scene does not consume game turns. The party returns to the same
  turn, phase and active hero. Tension on return comes from the
  scene's own consequences (a wandering monster picked up the trail),
  not from a clock the player can't see.

## 4. Hooks: how a side quest is offered

| hook | when it appears | who offers it |
|---|---|---|
| prologue | game start, after the story overlay, before the first move | the road in, a tavern rumour, a messenger |
| room | the moment a room is revealed (door opened) | an NPC figure in the room (any spare meeple), a shrine, a prisoner, a body with a letter |

Offered, not forced. The Journal (section 12) lists every discovered
side quest with a Begin button; a room-hooked scene can only be begun
while a hero stands in that room. "Required" means required to WIN,
not required to play right now. The party may walk on and come back.

Required side quests hook at the prologue or in a room the validator
proves is on the way: on the fence skeleton (never cut), not the
objective room, and closer to the stairway (in doors) than the
objective room, so the party meets the hook before the finale.

An NPC hook emits a placement instruction ("Place a figure for Old
Hessa at square [x,y]") through the existing placement queue. The NPC
occupies no square in the engine and blocks nothing.

## 5. Scene structure and the time budget

A scene is a small directed graph of passages.

- 5 to 10 passages; the longest path 7 deep. Each passage 60-120 words
  of prose and 2-3 choices. At ~1 minute per passage plus a die roll or
  two, that is the 10-15 minutes.
- Terminal passages carry an outcome (`success | partial | failure`),
  an effect bundle (section 6) and a short epilogue.
- The graph is acyclic, with one exception: a scene may declare at
  most ONE retry edge (a failed test may be attempted again at a stated
  cost). That is how "the old man's second ritual costs you a Body
  Point" is expressed without letting the player loop for free.
- Choices may be tagged with a requirement the client filters on:
  `hero` (barbarian/dwarf/elf/wizard), `element` (a spell element the
  party holds with at least one card unspent -- spellbooks and
  spellsCast are digital, so this is exact), or a scene `flag` set by an
  earlier passage. Every passage must keep at least one untagged
  choice, so no party is dead-ended by its composition.

### Tests (dice), on the app's existing terms

| test | who rolls | what the app asks |
|---|---|---|
| `combat_dice` (1-3 dice) | hero, physical | "report skulls" (0-3), same one-click row as defence |
| `mind` / `body` | hero, physical red die vs their own sheet | "Did you roll under your Mind Points?" yes/no -- the app never learns the value |
| `zargon` | app | app rolls and shows the result; nothing to report |
| `foe` (phase 2) | both | a single scene foe with digital Body Points; hero attacks report skulls, the foe's attacks arrive as pendingDefenses prompts -- the SAME queue Zargon's turn uses |

Spells in a scene (phase 2): attack spells at a scene foe apply through
the existing hero_spells path; a healing or utility spell is an
announced choice. Cast cards are spent for the quest as usual.

## 6. Effects: the closed vocabulary

Everything a choice can do. Priced in "boon points" so the generator
can't hand out too much; the validator enforces the caps.

App-owned (the engine applies them):

| effect | what happens | points |
|---|---|---|
| `break_gate` | the required gate opens (section 7) | required only |
| `crack_gate` | the gate weakens to hard mode (section 8) | required only |
| `grant_artifact {artifactId}` | the physical card is handed to a hero; recorded on the game as held (placement-only today, same as chest loot) | 3 |
| `weaken_monster {monsterId, body|defend: -1}` | a named monster's digital stats drop | 2 |
| `remove_monster {monsterId}` | an ally slays it, it deserts | threat / 4 |
| `reveal_traps {room}` / `reveal_secret_doors {room}` | as if searched, marked found | 1 |
| `ward_hero {heroId, attacks: N}` (phase 2) | Zargon's next N attacks on that hero roll one die fewer -- Zargon's dice, so fully enforceable | 2 |
| `spawn_wandering` | a wanderer at the frontier, existing spawn code | -1 |
| `miss_turn {heroId}` | heroStatus missesTurns, as Tempest does | -1 |

Announced (the player applies them at the table):

| effect | app says | points |
|---|---|---|
| `announce_reward {gold|potion|equipment|body, text}` | "Old Hessa presses 50 gold into your hand -- add it to your sheet" | gold 1, potion 2, equipment 2, body 1 |
| `announce_cost {body|gold, text}` | "The thorns take 1 Body Point from each hero" | -1 |
| `armory_visit` | the Armory reminder (section 9) | 0, town scenes only |

Caps: an optional scene's best terminal <= 4 points and its worst >= -2;
a required scene's success MUST include `break_gate`, its failure MUST
include `crack_gate` (the engine adds it if the model forgot), and its
reward on top <= 2. Named monsters referenced by effects must exist in
the quest. `grant_artifact` obeys the one-physical-card rule already in
validator/artifacts.py: never the same artifact twice across objective,
chest loot and side quests.

## 7. Required side quests: what the gate is

The gate is on the objective, chosen by the objective type, and the
main quest's own text explains it. The engine already has one choke
point for each.

| objective | gate | engine hook | what the party sees |
|---|---|---|---|
| `kill_boss` | **ward**: the boss takes no damage from hero attacks or attack spells | `_apply_hero_attack`, hero_spells damage path: skulls resolve to 0 wounds while `monsters.<id>.warded` | "Your blade turns on the ward. (Journal: The Black Candle)" and a ring on the boss token |
| `find_artifact` / `rescue` / `reach_exit` | **seal**: reaching the room does not complete the objective | `_mark_objective_if_complete` checks `game.gate.open` first | "The vault is sealed by the rite. (Journal: ...)" |
| horde (phase 3, new objective flavour) | **source**: a wanderer spawns every Zargon turn until closed | Zargon-turn spawn | the flood stops when the source is closed |

`game.gate = {sideQuestId, kind, state: closed|open|cracked}` is game
state, so undo and refresh behave.

## 8. Failure: fail forward, never dead-end

What narrative campaign games do, as a body of practice rather than
any one title: a failed side scenario changes the story and costs the
party something, but the campaign goes on. Tabletop RPG design has a
name for it, "fail forward" (or "success at a cost"): a failed roll
moves the story to a worse place instead of stopping it. The failure
mode to avoid is the one where the party stands outside the boss room
unable to win and unsure why.

Rules adopted:

- **Optional, failed**: no reward; one sting from the negative effects
  (a wound announced, a lost turn, a wanderer on the trail, the NPC
  dies and takes their secret with them). The main quest is untouched.
- **Required, failed**: `crack_gate`. The finale is now possible but
  harder, and the text says so.
  - ward -> cracked: the boss becomes vulnerable but gains +1 defend
    die and +1 Body Point (digital stats, so enforced), and a wanderer
    spawns at the frontier.
  - seal -> forced: the party may still complete the objective; doing
    so costs every hero 1 announced Body Point and spawns a wanderer.
- **Required, never attempted**: the party can always walk into the
  finale. The app tells them why it isn't working and names the scene
  in the Journal. If the hook room was revealed and the scene never
  begun, the log line says where to go back to.
- **Retry**: only through the scene's own single retry edge, at the
  cost it states. Undo remains the escape hatch for a misreported die,
  as everywhere else.
- **Invariant, validator-enforced**: every required scene has at least
  one `success` terminal reachable with untagged choices only, and the
  engine guarantees a gate can never stay `closed` after a required
  scene ends -- it is `open` or `cracked`.

## 9. Town scenes and the Armory

The 1989 rulebook opens the Armory between quests ("What Happens
Between Quests?": buy weapons and armor with accumulated gold). A town
scene is the one time the party is, in the fiction, standing in front
of it mid-quest. So every town-set scene carries a fixed beat the
generator must include (`armory_visit`):

> You are in town. The Armory is open -- normally a between-quests
> visit, but you are here now. Use the physical Armory card and your
> own gold; the app tracks neither. (House rule: buying mid-quest.
> Skip it if you'd rather keep to the book.)

The beat is a pause with a Continue button, never a form. The plain
between-quests reminder (no house-rule line) sits on the Quest
Complete banner for every game, traditional or expanded -- the
rulebook's rule applies whatever the variant, and the Journal only
exists in expanded games.

Only town scenes ever mention the Armory (owner's call). Every other
setting rewards the party with something FOUND: an Artifact card, or an
announced piece of equipment, potion or purse of gold that the story
puts in their hands. The generator is told this in so many words, so a
cave never ends in a shop.

## 10. Generation pipeline

Two callables, because one could not fit both inside the 8-minute
callable limit (the first live run timed out and lost a quest that had
already validated).

1. `generate_quest` rolls the required coin (server RNG, 1 in 3) and,
   if it lands, adds a line to the main prompt: the objective is
   warded/sealed and the backstory must say by what.
2. The main quest generates and validates exactly as today, and is
   SAVED at once with mode "expanded", sideQuestsStatus "pending" and
   sideQuestPlan {required}. The response says sideQuestsPending.
3. The client calls `generate_side_quests(questId)`: a second model
   call, its own 480-second budget, with the saved quest as context
   (title, backstory, objective, rooms used, named monsters, artifacts
   already placed), heroCount, the required decision and gate kind,
   the settings list, the effects catalog with prices and caps, and
   the passage limits. Its schema is its own (the quest's already
   saturated the grammar budget once, see generator/client.py).
4. Validate (section 11). Retry up to 2 times with the errors, like
   quests. Success merges sideQuests, gate and sideQuestsStatus
   "ready" onto the quest doc.
5. Failure records sideQuestsStatus "failed" and the errors. The quest
   is already saved and plays as traditional; the setup screen offers
   a retry. Never block quest generation on the side story.

Both calls take a client-chosen jobId and write their stage to
generationJobs/{jobId} as they go (writing attempt N, validating,
retrying with the first errors quoted, fencing, saving), which the
setup screen shows live beside the Generate button.

Same model as quest generation (generator/client.py MODEL). One extra
call, roughly 3-5k output tokens per quest.

## 11. Schema sketch (quest.sideQuests)

```json
{
  "id": "SQ1",
  "kind": "optional | required",
  "title": "The Black Candle",
  "setting": "town | forest | cave | shrine | road | vision",
  "hook": {
    "when": "prologue | room",
    "room": "R7",
    "npc": { "name": "Old Hessa", "figureHint": "any robed figure" },
    "text": "read-aloud: how the scene is offered"
  },
  "gate": { "kind": "ward | seal", "text": "why the finale is barred" },
  "start": "p1",
  "passages": {
    "p1": {
      "text": "60-120 words",
      "choices": [
        { "id": "c1", "label": "Follow the smoke", "next": "p2" },
        { "id": "c2", "label": "The Dwarf checks the lintel", "requires": { "hero": "dwarf" }, "next": "p3" },
        { "id": "c3", "label": "Force the grate", "test": { "kind": "combat_dice", "dice": 2, "needSkulls": 1, "success": "p4", "failure": "p5" } }
      ]
    }
  },
  "terminals": {
    "p6": { "outcome": "success", "effects": [ { "type": "break_gate" }, { "type": "announce_reward", "kind": "gold", "text": "..." } ], "text": "epilogue" },
    "p7": { "outcome": "failure", "effects": [ { "type": "crack_gate" } ], "text": "epilogue" }
  },
  "retry": { "from": "p5", "to": "p1", "cost": { "type": "announce_cost", "kind": "body", "text": "..." } }
}
```

Validator checks, in code: passage and depth limits; every `next`,
`success`, `failure` names a passage; every non-terminal passage keeps
one untagged choice; graph acyclic apart from the one declared retry
edge; every terminal reachable; outcome/effect caps of section 6;
required scenes' gate and terminal invariants of section 8; town
scenes include `armory_visit`; hook room on the skeleton and ahead of
the objective room; referenced monsters/artifacts exist; prose carries
no room ids or coordinates.

## 12. Game state, endpoints, UI

Game state (all undo-snapshotted, all refresh-safe):

```
sideQuests: { SQ1: { status: "hidden|available|active|success|partial|failure",
                     passageId, flags: [], history: [choiceIds], retried: false } }
pendingSideQuest: "SQ1" | null       -- locks the main game while active
gate: { sideQuestId, kind, state }   -- required scenes only
artifactsHeld: { ringOfReturn: "elf" } -- placement-only record, as chest loot is
```

Endpoints: `begin_side_quest(gameId, sideQuestId)`, `advance_side_quest(gameId,
choiceId, report?)` where `report` is the die result the choice's test
asks for (skull count, or yes/no). One passage per call, each a
transaction with an undo snapshot labelled "the side quest step".
Terminal passages apply their effects in the same write and clear
`pendingSideQuest`. Every passage's prose and every effect is logged
under the current turn, so turn narration and the chronicle see the
side story without any new prompt plumbing.

UI:
- **Journal** panel in the rail, below the action panel: each known
  side quest with its status, a Begin button (enabled when its hook
  condition holds), and, for a required one, the gate line ("The
  Warlock is warded until this is done"). The Journal also holds the
  between-quests Armory reminder once a quest is complete.
- **Side-quest page**: full width, board hidden. Title and setting
  banner, the passage prose in the story-so-far voice, choice buttons,
  and the test prompt in the same one-click die rows the defence and
  spear panels use. A Journal-style progress line ("passage 4 of at
  most 7"). Undo in the header works on scene steps like anything
  else. No Abandon button: beginning a scene is the commitment; the
  scene is short by construction.
- A room-hook reveal shows a quiet "Someone here has a task for you"
  line in the placement alert, not a modal.

## 13. Story threads onward

- Turn narration and the chronicle already build from the log, so a
  scene's passages and outcome reach them for free.
- Campaign continuity (`continuesFromGameId`) gains one input: the
  side quests' outcomes, including the ones never attempted. A sequel
  may pick up a failed or ignored thread. Narrative only, as
  continuity already is.
- Quests generated before this exists have no side quests. A later
  "Add side quests" button on the setup screen could backfill one
  quest at a time; not v1.

## 13b. As built (phase 1, Sept 2026)

Implemented as designed with these deltas: the scene page is a
full-page overlay rather than a route (same effect, no router); the
epilogue is held client-side after the terminal write clears
pendingSideQuest, until the player presses "Back to the dungeon";
`weaken_monster` takes a `stat` field (body | defend); a `dazed` hero
status carries miss_turn; the required scene's hook-room rule is
"fewer doors from the stairway than the objective room" (the fence
skeleton check reduced to that); CLAUDE.md's design-artifacts entry
lists every module. Phases 2-3 remain open.

## 14. Phasing

- **Phase 1**: schema, generator prompt, validator; storage on the
  quest; Journal; the side-quest page with prose, choices, hero and
  element tags, `combat_dice` and `mind`/`body` tests; effects:
  announced rewards and costs, `grant_artifact`, `weaken_monster`,
  `reveal_*`, `spawn_wandering`, `miss_turn`; prologue and room hooks;
  the required coin with ward and seal gates; fail-forward outcomes;
  the Armory beat.
- **Phase 2**: scene foes through the defence queue; spells in scenes;
  `ward_hero`; `remove_monster`.
- **Phase 3**: horde objective and its source gate; sequel threads from
  side-quest outcomes; backfill for old quests.

## 15. Owner's answers (Sept 2026)

1. Required chance: 1 in 3. Yes.
2. Armory: only when the scene is set in a town. Elsewhere the party
   finds an item instead, magical or otherwise (section 9). The
   between-quests reminder stays.
3. A room-hooked scene stays available when the party returns.
4. Added after the fact: the whole thing is an optional variant. The
   players choose traditional or expanded (section 0).
