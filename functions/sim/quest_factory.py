"""Synthetic quests for the simulator, built on the real board.

The LLM generator can't be in this loop -- thousands of quests, offline,
deterministic. What matters for balance is the SHAPE the engine sees:
rooms joined by doors, monsters worth N threat points spread across
them, an objective at the far end and a walk home. Backstory and
flavour text are exactly what doesn't matter, so they aren't generated.

Every quest is seeded, so a run is reproducible and two rule sets can
be compared over the identical set of dungeons -- which is the whole
point (same maps, same dice, one rule changed).
"""

from __future__ import annotations

import random

from generator.fence import apply_fence
from validator.balance import BASELINE_BUDGET, HERO_BUDGET_RATIO, ROOM_CAP_BY_HERO_COUNT
from validator.catalogs import CORRIDOR, Catalogs
from validator.geometry import footprint_cells

Coord = tuple[int, int]

ROOMS_BY_SIZE = {"short": (4, 6), "full": (8, 12)}

# Cheap-to-mid types make up the bulk of a real quest's roster; a boss is
# picked separately.
COMMON_TYPES = ("goblin", "orc", "skeleton", "zombie", "fimir")
BOSS_TYPES = ("chaos_warrior", "gargoyle", "mummy", "fimir")


def _stairway_pos(board, room_id: str) -> Coord | None:
    squares = board.room_squares[room_id]
    for x, y in sorted(squares):
        if {(x + 1, y), (x, y + 1), (x + 1, y + 1)} <= squares:
            return (x, y)
    return None


def _corridor_door(board, room_id: str, used: set) -> list | None:
    """A door from this room onto the corridor network, avoiding edges
    another room has already claimed.
    """
    for square in sorted(board.room_squares[room_id]):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbour = (square[0] + dx, square[1] + dy)
            if board.area_of.get(neighbour) == CORRIDOR and (square, neighbour) not in used:
                used.add((square, neighbour))
                return [list(square), list(neighbour)]
    return None


def _room_distance(board, a: str, b: str) -> int:
    """Rough centre-to-centre distance, for ordering rooms by how deep
    into the dungeon they are.
    """
    def centre(room_id):
        squares = sorted(board.room_squares[room_id])
        return (
            sum(s[0] for s in squares) / len(squares),
            sum(s[1] for s in squares) / len(squares),
        )

    ax, ay = centre(a)
    bx, by = centre(b)
    return abs(ax - bx) + abs(ay - by)


def build_quest(
    catalogs: Catalogs,
    *,
    hero_count: int,
    size: str = "full",
    budget_multiplier: float = 1.0,
    boss_spells: tuple = (),
    seed: int = 0,
) -> dict:
    """A quest whose monster roster is worth roughly the calibrated
    budget for this party, times `budget_multiplier`. Sweeping the
    multiplier is how the sim finds what a rule change costs.
    """
    rng = random.Random(seed)
    board = catalogs.board

    stair_candidates = [r for r in sorted(board.room_squares) if _stairway_pos(board, r)]
    stair_room = rng.choice(stair_candidates)
    stair_pos = _stairway_pos(board, stair_room)

    low, high = ROOMS_BY_SIZE[size]
    room_count = rng.randint(low, high)
    others = sorted((r for r in board.room_squares if r != stair_room),
                    key=lambda r: _room_distance(board, stair_room, r))
    # Nearby rooms, then the objective as deep as the quest goes.
    picked = others[: max(room_count - 1, 1)]
    objective_room = picked[-1]

    used_edges: set = set()
    doors = []
    for i, room_id in enumerate([stair_room, *picked]):
        squares = _corridor_door(board, room_id, used_edges)
        if squares:
            doors.append({"id": f"D{i}", "squares": squares, "state": "closed"})

    target = BASELINE_BUDGET * HERO_BUDGET_RATIO[hero_count] * budget_multiplier
    room_cap = ROOM_CAP_BY_HERO_COUNT[hero_count]
    stair_squares = set(footprint_cells(stair_pos, (2, 2)))

    rooms: dict = {}
    spent = 0
    monster_index = 0
    boss_id = None

    # The objective's boss goes down first, then the rest of the budget
    # is spread over the other rooms.
    boss_choices = BOSS_TYPES
    if boss_spells:
        # A boss holding Chaos spells has to be a type that can cast
        # them at all (validator.balance.caster_types).
        boss_choices = [t for t in BOSS_TYPES if catalogs.monsters[t].get("caster")] or BOSS_TYPES
    boss_type = rng.choice(boss_choices)
    boss_entry = catalogs.monsters[boss_type]
    boss_squares = sorted(board.room_squares[objective_room] - stair_squares)
    monster_index += 1
    boss_id = f"M{monster_index}"
    rooms[objective_room] = {
        "revealText": "",
        "monsters": [
            {
                "id": boss_id,
                "type": boss_type,
                "name": "The Boss",
                "pos": list(boss_squares[0]),
                **({"spells": list(boss_spells)} if boss_spells else {}),
            }
        ],
        "furniture": [],
        "traps": [],
    }
    spent += boss_entry["threatCost"]

    fill_order = [r for r in picked if r != objective_room] + [objective_room]
    occupied = {tuple(boss_squares[0])}
    guard = 0
    while spent < target and guard < 200:
        guard += 1
        room_id = fill_order[guard % len(fill_order)]
        room = rooms.setdefault(room_id, {"revealText": "", "monsters": [], "furniture": [], "traps": []})
        if len(room["monsters"]) >= room_cap:
            continue
        mtype = rng.choice(COMMON_TYPES)
        entry = catalogs.monsters[mtype]
        if spent + entry["threatCost"] > target * 1.05:
            continue
        free = [sq for sq in sorted(board.room_squares[room_id] - stair_squares) if sq not in occupied]
        if not free:
            continue
        pos = free[0]
        occupied.add(pos)
        monster_index += 1
        room["monsters"].append({"id": f"M{monster_index}", "type": mtype, "pos": list(pos)})
        spent += entry["threatCost"]

    quest = {
        "id": f"sim-{seed}",
        "title": "Simulated Quest",
        "objective": {
            "type": "kill_boss",
            "description": "Kill the boss.",
            "target": {"monsterId": boss_id, "room": objective_room},
        },
        "wanderingMonster": "orc",
        "stairway": {"room": stair_room, "pos": list(stair_pos)},
        "blockedSquares": [],
        "startingRoom": "stairway",
        "doors": doors,
        "corridorTraps": [],
        # Escape needs a marked square; the stairway room's own corner
        # is a fine "safe place known only to Zargon".
        "escapeDestination": list(stair_pos),
        "rooms": rooms,
        "completionText": "",
        "generationParams": {"heroCount": hero_count, "difficulty": "standard", "size": size},
    }
    apply_fence(quest, catalogs)
    quest["threatSpent"] = spent
    return quest
