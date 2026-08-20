# HeroQuest Solo Zargon — Data Model v0.1

Three layers, separated so the AI generator only writes layer 3:

1. **Static board data** — built once, never changes
2. **Static rules data** — 1989 NA edition reference tables
3. **Quest definition** — AI-generated per quest
4. **Game state** — runtime, mutated during play

---

## 1. Static board data (`board.json`)

The official board: 26×19 grid, fixed walls, 22 rooms + corridor squares.
No doorways or stairway are stored here — see the amendment in CLAUDE.md:
the 1989 board has no printed doors, so both are quest-owned (section 3).

```json
{
  "width": 26,
  "height": 19,
  "rooms": [
    { "id": "R1", "label": "wood parquet", "squares": [[1,1],[2,1],[3,1],[1,2],[2,2],[3,2]] }
  ],
  "corridorSquares": [[0,0],[0,1]]
}
```

- Coordinates: `[x, y]`, origin top-left, x → right, y → down.
- Every square belongs to exactly one area: one room's `squares`, or
  `corridorSquares`. No square appears in two areas (verified against
  the actual file). "Area" is the unit reachability and doors operate
  on — see section 3's door notes.

## 2. Static rules data (`monsters.json`, NA 1989 stats)

```json
{
  "orc":          { "move": 8, "attack": 3, "defend": 2, "body": 1, "mind": 2 },
  "goblin":       { "move": 10, "attack": 2, "defend": 1, "body": 1, "mind": 1 },
  "skeleton":     { "move": 6, "attack": 2, "defend": 2, "body": 1, "mind": 0 },
  "zombie":       { "move": 5, "attack": 2, "defend": 3, "body": 1, "mind": 0 },
  "mummy":        { "move": 4, "attack": 3, "defend": 4, "body": 2, "mind": 0 },
  "fimir":        { "move": 6, "attack": 3, "defend": 3, "body": 2, "mind": 3 },
  "chaos_warrior":{ "move": 7, "attack": 4, "defend": 4, "body": 3, "mind": 3 },
  "gargoyle":     { "move": 6, "attack": 4, "defend": 5, "body": 4, "mind": 4 }
}
```

Named bosses reference a base type with stat overrides (see quest schema).

## 3. Quest definition (AI generator output)

```json
{
  "id": "quest-uuid",
  "title": "The Tomb of the Ashen King",
  "backstory": "Read-aloud intro text...",
  "objective": {
    "type": "kill_boss | find_artifact | reach_exit | rescue",
    "description": "Player-facing objective text",
    "target": { "monsterId": "M7" }
  },
  "wanderingMonster": "orc",
  "stairway": { "room": "R4", "pos": [2, 5] },
  "blockedSquares": [[12, 4], [12, 5]],
  "startingRoom": "stairway",
  "doors": [
    { "id": "D1", "squares": [[3, 2], [4, 2]], "state": "open | closed | secret" }
  ],
  "corridorTraps": [
    { "type": "pit | falling_block", "pos": [6, 0] }
  ],
  "rooms": {
    "R3": {
      "revealText": "Optional narrative on first reveal",
      "monsters": [
        {
          "id": "M7",
          "type": "chaos_warrior",
          "name": "The Ashen King",
          "pos": [5, 3],
          "overrides": { "body": 4, "attack": 5 }
        }
      ],
      "furniture": [
        { "type": "tomb", "pos": [4, 2], "orientation": "N",
          "contains": { "trap": "spear", "treasure": "artifact | text" } }
      ],
      "traps": [
        { "type": "pit | falling_block", "pos": [6, 4] }
      ],
      "treasure": "deck | none | { special }"
    }
  },
  "completionText": "Read-aloud victory text"
}
```

Doors are quest-owned (see amendment below): each door names the two
adjacent squares its wall edge sits between, not a board-catalog id —
the board has no printed doorways to reference. `squares` order doesn't
matter; the pair must be orthogonally adjacent and in two different
areas (two rooms, or a room and the corridor). Corridor-to-corridor
edges never need a door — the corridor is one open network.

`corridorTraps` is a top-level list, parallel to a room's `traps`, for
the "at most 3 in corridors total" cap in
quest-generator-design.md section 5 — traps placed in the corridor
rather than inside a room.

If the objective is only reachable through a secret door (no route
through open/closed doors), the quest must set
`objective.secretPathHint: { "room": "R_id", "text": "..." }`, where
`room` is itself reachable without any secret door. Without a valid
hint, an objective reachable only via secret door fails validation.

Notes:
- Empty rooms simply omitted from `rooms` — searches there use the treasure deck.
- `treasure: "deck"` = standard deck draw (physical); `special` = quest treasure the app narrates.
- Furniture can carry traps/treasure (chest, tomb) per 1989 quest book conventions.
- `stairway` is quest-owned (placed tile, 2x2, any room); the board has no
  fixed stairway and no printed doorways — doors are quest-defined wall edges.
- `blockedSquares`: impassable + block LOS; player places the physical
  blocked-square tiles when revealed.
- Entity counts are capped by owned physical components (see CLAUDE.md).

## 4. Game state (Firestore, mutated at runtime)

```json
{
  "questId": "quest-uuid",
  "turn": 14,
  "phase": "hero | zargon",
  "heroes": [
    { "id": "barbarian", "pos": [12, 9], "active": true }
  ],
  "revealed": { "rooms": ["R12", "R3"], "corridorSquares": [[11,8]] },
  "monsters": {
    "M7": { "pos": [5,3], "currentBody": 2, "alive": true }
  },
  "doors": { "D1": "open" },
  "trapsTriggered": ["R3-T1"],
  "searched": { "R3": { "treasure": true, "traps": false } },
  "log": [ { "turn": 14, "text": "Fimir attacks Barbarian: 2 skulls" } ]
}
```

- Hero state is positions only — no BP, gold, or inventory (tracked physically).
- `searched` enforces the once-per-room treasure search rule.
- `log` doubles as the Zargon turn narration history.

---

## Key design decisions

- **AI writes layer 3 only.** Board geometry and monster stats are code-owned; the generator can't break rules by hallucinating stats or invalid squares.
- **Validation pass required.** Generator output is validated against board.json (positions inside the named room, no overlaps, doorway IDs exist) before a quest is playable. Invalid output → regenerate.
- **Room IDs, not coordinates, drive fog of war.** Reveal is per-room/per-corridor-square, matching how a human Zargon populates a room when the door opens.
