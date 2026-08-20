"""Builds the LLM prompt per design/generator-prompt.md. Placeholders in
that doc are filled here from the same catalogs/constants the validator
uses, so the prompt and the validator can never disagree about a number.
"""

from __future__ import annotations

import json
import random

from validator.balance import (
    BASELINE_BUDGET,
    BUDGET_TOLERANCE,
    HARD_DIFFICULTY_MULTIPLIER,
    HERO_BUDGET_RATIO,
    MIN_DEPTH_BY_SIZE,
    ROOM_CAP_BY_HERO_COUNT,
    WANDERING_MAX_COST_LOW_HERO_COUNT,
)
from validator.catalogs import Catalogs

SIZE_ROOM_RANGE = {"short": "4-6", "full": "8-12"}


def _room_catalog_json(catalogs: Catalogs) -> str:
    rooms = [
        {"id": room_id, "squares": sorted(list(squares))}
        for room_id, squares in sorted(catalogs.board.room_squares.items())
    ]
    return json.dumps(rooms)


def _furniture_catalog_json(catalogs: Catalogs) -> str:
    furniture = {
        name: {"footprint": list(entry["footprint"]), "owned": entry["owned"]}
        for name, entry in catalogs.furniture.items()
    }
    return json.dumps(furniture, sort_keys=True)


def _monster_cost_line(catalogs: Catalogs) -> str:
    return " ".join(
        f"{name}({entry['threatCost']})"
        for name, entry in sorted(catalogs.monsters.items(), key=lambda kv: kv[1]["threatCost"])
    )


def _physical_caps_lines(catalogs: Catalogs) -> str:
    room_caps = ", ".join(
        f"{name} {entry['roomCap']}"
        for name, entry in sorted(catalogs.monsters.items(), key=lambda kv: kv[0])
    )
    furniture_caps = ", ".join(
        f"{name} x{entry['owned']}" for name, entry in sorted(catalogs.furniture.items())
    )
    return (
        f"Per-ROOM monster caps (minis recycle across the quest, but one room can "
        f"never contain more of a type than owned): {room_caps}.\n"
        f"Furniture per quest (hard-capped at owned counts): {furniture_caps}.\n"
        f"Doors per quest: 21 total."
    )


def _budget_range(hero_count: int, difficulty: str) -> tuple[float, float, float]:
    target = BASELINE_BUDGET * HERO_BUDGET_RATIO[hero_count]
    if difficulty == "hard":
        target *= HARD_DIFFICULTY_MULTIPLIER
    return target * (1 - BUDGET_TOLERANCE), target * (1 + BUDGET_TOLERANCE), target


def _wandering_constraint(hero_count: int) -> str:
    if hero_count <= 2:
        return f"cost <= {WANDERING_MAX_COST_LOW_HERO_COUNT} (fimir or cheaper)"
    return "any type"


def rooms_with_2x2_fit(catalogs: Catalogs) -> list[str]:
    """Rooms with at least one contiguous 2x2 sub-block -- the stairway's
    fixed footprint. Used to pick a valid candidate for pick_stairway_room.
    """
    fits = []
    for room_id, squares in catalogs.board.room_squares.items():
        if any((x + 1, y) in squares and (x, y + 1) in squares and (x + 1, y + 1) in squares for x, y in squares):
            fits.append(room_id)
    return fits


def pick_stairway_room(catalogs: Catalogs, rng: random.Random | None = None) -> str:
    """Randomly pre-selects the starting room and hands it to the model
    as a hard constraint, rather than leaving "which room is the
    stairway in" to the model's free choice. In practice the model has
    a very strong prior toward the first room in the catalog regardless
    of sampling settings -- every quest generated during testing started
    in the exact same physical corner of the board. Picking it in code
    guarantees real variety; the model still designs everything else
    (room usage, monsters, objective, story) around wherever it lands.
    """
    rng = rng or random
    return rng.choice(rooms_with_2x2_fit(catalogs))


def build_system_prompt(params: dict, catalogs: Catalogs, stairway_room: str) -> str:
    hero_count = params["heroCount"]
    difficulty = params.get("difficulty", "standard")
    size = params.get("size", "full")
    theme = params.get("theme", "a dungeon of the owner's choosing")

    budget_min, budget_max, _ = _budget_range(hero_count, difficulty)
    room_cap = ROOM_CAP_BY_HERO_COUNT[hero_count]
    min_depth = MIN_DEPTH_BY_SIZE[size]
    room_range = SIZE_ROOM_RANGE[size]

    return f"""You are a quest designer for the 1989 North American edition of HeroQuest.
You design a complete quest as a single JSON object matching the schema below.
You control story, mood, room selection, monster/furniture/trap placement,
door layout, and objective. You do NOT control rules or stats — monster stats
are fixed, and your output is validated by code against the board geometry
and balance budget. Invalid output is rejected, so follow every constraint.

### BOARD
The board is a 26x19 grid. Coordinates are [x,y], origin top-left, x right,
y down. Rooms (id, and the exact squares each contains):
{_room_catalog_json(catalogs)}
Squares not listed in any room are corridor. Rooms connect to corridors and
to each other ONLY through doors you declare. A door occupies one wall edge
between two adjacent squares in different areas.

### MONSTERS (fixed stats, threat cost in parentheses)
{_monster_cost_line(catalogs)}
A named boss = one monster with `name` and optional stat `overrides`
(overrides add its extra threat: +1 per added body or attack die; only
attack/body increases affect cost). If you use `overrides`, the schema
requires all five stats (move, attack, defend, body, mind) — repeat the
monster's base value for any stat you are not changing.

### FURNITURE (footprint w x h, max count = physical pieces owned)
{_furniture_catalog_json(catalogs)}
Chests and tombs may contain a trap, treasure, or both via `contains`. If
you use `contains`, the schema requires both `trap` and `treasure` —
use "none" for whichever one doesn't apply.

### ROOM OBJECT
Every entry in `rooms` must include all four fields: `revealText`,
`monsters`, `furniture`, `traps` — use an empty array `[]` for any that
don't apply to that room (e.g. a corridor-adjacent room with no
furniture still needs `"furniture": []`).

### PHYSICAL COMPONENT CAPS
{_physical_caps_lines(catalogs)}
Blocked squares: use sparingly (limited tiles).

### QUEST PARAMETERS
- heroCount: {hero_count}
- difficulty: {difficulty}
- size: {size} ({room_range} populated rooms)
- monster budget: total threat cost MUST be {budget_min:.0f}-{budget_max:.0f}
- max monsters in any one room: {room_cap}
- theme: {theme}
- stairway room: {stairway_room} (pre-selected -- see hard constraint 5)

### HARD CONSTRAINTS
1. Every position must be a square inside the declared room. No two entities
   (monster, furniture, stairway) may overlap. Traps may share a square with
   nothing else.
2. Doors only on wall edges shared by two areas. Every populated room must be
   reachable from the stairway through your doors (corridors are open paths).
   A door is `{{"id": "D1", "squares": [[x1,y1],[x2,y2]], "state": "open|closed|secret"}}`
   -- declare an ordinary door as "closed": EVERY door starts closed in
   play (a hero must stop at it and have Zargon open it), so "open" is
   never the right choice. Use "secret" (must be found by searching)
   deliberately.
   — the two squares are the wall edge itself, one on each side.
3. The objective room must be at least {min_depth} doors deep from the
   stairway room and never adjacent to it.
4. Secret doors are optional shortcuts, never the only route to the objective.
   If you do make the objective secret-door-only, set
   `objective.secretPathHint` to a room reachable without secret doors.
5. The stairway (2x2) MUST be placed in room {stairway_room} -- this room
   is pre-selected, not your choice. Declare it in `stairway.room` with a
   `pos` such that the 2x2 footprint fits fully inside that room.
6. Exactly one wandering monster type. {_wandering_constraint(hero_count)}
7. Traps: at most 1 per room, at most 3 total in `corridorTraps` (traps placed
   in corridor squares rather than inside a room). Trap types: pit,
   falling_block, spear (pit and falling block have physical tiles; a
   spear trap has none -- it is gone once sprung).
7b. You may declare blockedSquares (impassable, block line of sight,
   rendered with the physical blocked-square tiles). They must never make
   a populated room or the objective unreachable.
8. Unpopulated rooms: omit them from `rooms`. They default to empty + treasure deck.
9. Do not invent room ids, monster types, or furniture types.

### STYLE
- backstory: 80-200 words, second person, read-aloud at quest start.
  End with the objective stated plainly.
- revealText per populated room: <= 40 words, atmosphere only, never spoil
  hidden traps or secret doors.
- completionText: 40-100 words.
- Vary room usage across the board; don't cluster everything in one quadrant.

### OUTPUT
Return a JSON object matching the schema you were given, no markdown, no commentary."""


def build_user_message(params: dict) -> str:
    size = params.get("size", "full")
    hero_count = params["heroCount"]
    difficulty = params.get("difficulty", "standard")
    theme = params.get("theme", "a dungeon of the owner's choosing")
    return f"Design a {size} quest for {hero_count} hero(es), difficulty {difficulty}.\nTheme: {theme}"


def build_retry_message(errors: list) -> str:
    error_list = "\n".join(f"- {e}" for e in errors)
    return (
        "Your previous quest failed validation. Fix ONLY these errors and "
        f"return the corrected full JSON:\n{error_list}"
    )
