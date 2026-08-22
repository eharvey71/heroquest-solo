# Quest Generator + Validator — Design v0.1

Approach: fully AI-generated quests, made trustworthy by a code validator.
The LLM gets creative freedom over story, layout choices, and placement;
code enforces geometry, rules, and balance. Invalid output never reaches play.

---

## 1. Generator inputs

```json
{
  "theme": "free text or preset (undead crypt, orc warband, sorcerer's lair...)",
  "heroCount": 1-4,
  "difficulty": "standard | hard",
  "size": "short (4-6 rooms) | full (8-12 rooms)"
}
```

## 2. What the LLM receives (system prompt contents)

- Room catalog from board.json: id, dimensions, square list (so placements are legal)
- Monster catalog: NA 1989 stats + a threat cost per monster (see budget below)
- Furniture catalog: piece, footprint size, search rules (chest/tomb can hold traps or treasure)
- The quest JSON schema (from quest-schema.md, with doors + stairway now quest-owned)
- Hard constraints stated in prose AND enforced later in code:
  - Use only listed room ids and monster types
  - All positions inside the declared room's squares
  - Doors only on shared wall edges between two areas (room↔room or room↔corridor)
  - Spend the monster budget for this heroCount within ±10%
  - Boss/objective room must NOT be adjacent to the starting room
  - Every used room reachable from the stairway via declared doors

## 3. Monster budget (from the Zargon Deck sim)

Threat cost per monster ≈ attack + defend + body:
goblin 4, skeleton 5, zombie 6, orc 6, fimir 8, mummy 9, chaos_warlock 10,
chaos_warrior 11, gargoyle 13.

| heroCount | budget (full quest) | max monsters/room | Zargon behavior weights |
|-----------|--------------------|-------------------|-------------------------|
| 4 | 100% (baseline ≈ quest-book density) | 4 | normal 72% / cunning 24% / wandering 4% |
| 3 | 85% | 3 | normal 76% / cunning 20% / wandering 4% |
| 2 | 70% (+1 healing potion/hero, app reminds at start) | 3 | normal 80% / cunning 16% / wandering 4% |
| 1 | 55% (+hero takes 2 actions/turn, app enforces in turn UI) | 2 | normal 84% / cunning 12% / wandering 4% |

Baseline budget calibrated once by costing 2-3 official quests; sim showed
79-92% win at these ratios. `difficulty: hard` = +15% budget + 1 extra
wandering-monster weight point.

Turn weights replace the physical card draw: each Zargon turn, the app rolls
the turn type from these weights (the digital Zargon Deck).

## 4. Generation pipeline

```
params → build prompt → LLM (JSON mode) → parse
  → VALIDATE (code) → pass → save quest to Firestore
                    → fail → retry with error list appended (max 3)
  → auto-repair pass for trivial issues before retrying:
      - position 1 square outside room → clamp to nearest legal square
      - budget within ±20% → add/remove cheapest monster
      - anything structural (doors, reachability) → full retry
```

## 5. Validator checks

Geometry
- [ ] every room id / monster type / furniture type exists in catalogs
- [ ] every monster/furniture/trap position is inside its declared room
- [ ] no two entities share a square; furniture footprints fit
- [ ] every door sits on a wall edge shared by exactly two areas
- [ ] stairway placed in a valid room, footprint 2x2 fits

Reachability (BFS from stairway through declared doors + corridor network)
- [ ] all populated rooms reachable
- [ ] objective reachable; secret doors not the ONLY path to the objective
      unless quest flags it intentionally (and then a hint exists in a
      searchable room on the main path)

Balance
- [ ] monster budget within ±10% of the heroCount target
- [ ] per-room monster cap respected
- [ ] boss room not adjacent to start; at least N rooms deep (short: 3, full: 5)
- [ ] trap count ≤ 1 per room + 3 corridor traps max
- [ ] exactly one wandering monster type, cost ≤ fimir for 1-2 heroes

Narrative (soft checks, warn not fail)
- backstory 80-200 words; every populated room has revealText ≤ 40 words

## 6. Failure feedback loop

On validation failure the retry prompt appends machine-generated errors verbatim:
`"M3 at [6,2] is outside R5 (valid squares: ...)"`. This converges fast —
most failures fix in one retry. After 3 failures, surface the raw errors in
the UI rather than silently looping.

## 7. Where it runs

Cloud Function (Python) `generateQuest(params) → questId`:
prompt build + LLM call + validate + repair + Firestore write, all server-side.
Client never sees an unvalidated quest.
