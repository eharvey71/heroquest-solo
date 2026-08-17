"""Auto-repair pass for trivial validation failures, per
design/quest-generator-design.md section 4: fix what's cheap to fix before
burning a retry attempt on the LLM. Anything structural (bad doors, broken
reachability, wrong room ids) is left alone — that goes back to the LLM as
a full retry with the validator's error list.

Both repairs are best-effort: if there's nothing safe to do (no room has
capacity, no square is a clean clamp target), the quest is left as-is and
the next validate_quest() call reports it as a normal error.
"""

from __future__ import annotations

from validator.balance import (
    HERO_BUDGET_RATIO,
    BASELINE_BUDGET,
    BUDGET_TOLERANCE,
    HARD_DIFFICULTY_MULTIPLIER,
    ROOM_CAP_BY_HERO_COUNT,
    _monster_threat_cost,
)
from validator.catalogs import Catalogs
from validator.geometry import _footprint_cells

CLAMP_REPAIR_TOLERANCE = 1  # "1 square outside room", per the design doc
BUDGET_REPAIR_TOLERANCE = 0.20  # only attempt if within +/-20% of target
MAX_BUDGET_ADJUSTMENTS = 3


def _nearest_room_square(pos, room_squares):
    px, py = pos
    best, best_dist = None, None
    for sq in room_squares:
        dist = max(abs(sq[0] - px), abs(sq[1] - py))  # Chebyshev: "1 square outside" in any direction
        if best_dist is None or dist < best_dist:
            best, best_dist = sq, dist
    return best, best_dist


def clamp_out_of_room_positions(quest: dict, catalogs: Catalogs) -> bool:
    """Mutates quest in place. Returns True if anything was clamped."""
    board = catalogs.board
    repaired = False

    for room_id, room in quest.get("rooms", {}).items():
        room_squares = board.room_squares.get(room_id)
        if room_squares is None:
            continue  # unknown room id is structural, not clampable

        for entity in [*room.get("monsters", []), *room.get("traps", [])]:
            pos = entity.get("pos")
            if not (isinstance(pos, (list, tuple)) and len(pos) == 2):
                continue
            pos = tuple(pos)
            if pos in room_squares:
                continue
            nearest, dist = _nearest_room_square(pos, room_squares)
            if nearest is not None and dist <= CLAMP_REPAIR_TOLERANCE:
                entity["pos"] = list(nearest)
                repaired = True

    return repaired


def _occupied_squares_in_room(room: dict, catalogs: Catalogs) -> set:
    occupied = set()
    for m in room.get("monsters", []):
        pos = m.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            occupied.add(tuple(pos))
    for t in room.get("traps", []):
        pos = t.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            occupied.add(tuple(pos))
    for f in room.get("furniture", []):
        ftype = f.get("type")
        pos = f.get("pos")
        entry = catalogs.furniture.get(ftype)
        if entry is None or not (isinstance(pos, (list, tuple)) and len(pos) == 2):
            continue
        occupied.update(_footprint_cells(tuple(pos), entry["footprint"], f.get("orientation", "N")))
    return occupied


def _budget_target(hero_count: int, difficulty: str) -> float:
    target = BASELINE_BUDGET * HERO_BUDGET_RATIO[hero_count]
    if difficulty == "hard":
        target *= HARD_DIFFICULTY_MULTIPLIER
    return target


def _total_budget(quest: dict, catalogs: Catalogs) -> int:
    total = 0
    for room in quest.get("rooms", {}).values():
        for m in room.get("monsters", []):
            entry = catalogs.monsters.get(m.get("type"))
            if entry is not None:
                total += _monster_threat_cost(m, entry)
    return total


def _cheapest_monster_type(catalogs: Catalogs) -> str:
    return min(catalogs.monsters.items(), key=lambda kv: kv[1]["threatCost"])[0]


def _try_add_monster(quest: dict, catalogs: Catalogs, hero_count: int) -> bool:
    cheap_type = _cheapest_monster_type(catalogs)
    cheap_entry = catalogs.monsters[cheap_type]
    room_cap_total = ROOM_CAP_BY_HERO_COUNT[hero_count]

    for room_id, room in sorted(quest.get("rooms", {}).items()):
        room_squares = catalogs.board.room_squares.get(room_id)
        if room_squares is None:
            continue
        monsters = room.get("monsters", [])
        if len(monsters) >= room_cap_total:
            continue
        type_count = sum(1 for m in monsters if m.get("type") == cheap_type)
        if type_count >= cheap_entry["roomCap"]:
            continue
        occupied = _occupied_squares_in_room(room, catalogs)
        free = next((sq for sq in sorted(room_squares) if sq not in occupied), None)
        if free is None:
            continue
        existing_ids = {m.get("id") for m in monsters}
        new_id = next(f"M_repair{i}" for i in range(1000) if f"M_repair{i}" not in existing_ids)
        monsters.append({"id": new_id, "type": cheap_type, "pos": list(free)})
        room["monsters"] = monsters
        return True
    return False


def _try_remove_cheapest_monster(quest: dict, catalogs: Catalogs) -> bool:
    cheapest = None  # (cost, room, index)
    for room in quest.get("rooms", {}).values():
        for i, m in enumerate(room.get("monsters", [])):
            entry = catalogs.monsters.get(m.get("type"))
            if entry is None:
                continue
            cost = _monster_threat_cost(m, entry)
            if cheapest is None or cost < cheapest[0]:
                cheapest = (cost, room, i)
    if cheapest is None:
        return False
    _, room, index = cheapest
    del room["monsters"][index]
    return True


def adjust_budget_within_tolerance(quest: dict, params: dict, catalogs: Catalogs) -> bool:
    """Mutates quest in place. Returns True if anything was adjusted."""
    hero_count = params["heroCount"]
    difficulty = params.get("difficulty", "standard")
    target = _budget_target(hero_count, difficulty)
    low, high = target * (1 - BUDGET_TOLERANCE), target * (1 + BUDGET_TOLERANCE)
    repair_low = target * (1 - BUDGET_REPAIR_TOLERANCE)
    repair_high = target * (1 + BUDGET_REPAIR_TOLERANCE)

    repaired = False
    for _ in range(MAX_BUDGET_ADJUSTMENTS):
        total = _total_budget(quest, catalogs)
        if low <= total <= high:
            break
        if total < low:
            if total < repair_low or not _try_add_monster(quest, catalogs, hero_count):
                break
        else:
            if total > repair_high or not _try_remove_cheapest_monster(quest, catalogs):
                break
        repaired = True

    return repaired


def apply_auto_repair(quest: dict, params: dict, catalogs: Catalogs) -> bool:
    """Runs every repair pass. Returns True if anything changed."""
    clamped = clamp_out_of_room_positions(quest, catalogs)
    budget_adjusted = adjust_budget_within_tolerance(quest, params, catalogs)
    return clamped or budget_adjusted
