"""Balance checks: monster budget, per-room caps, boss depth, trap caps,
wandering monster, furniture/door physical caps.

Corresponds to design/quest-generator-design.md section 5 "Balance" and
CLAUDE.md's Balance system + Physical component caps.
"""

from __future__ import annotations

from collections import Counter, deque

from engine.chaos_spells import CHAOS_SPELLS

from .catalogs import Catalogs
from .reachability import NON_SECRET_STATES, _door_edges, _objective_target_room

# CLAUDE.md Balance system: budget ratio by hero count, calibrated baseline 120.
HERO_BUDGET_RATIO = {4: 1.00, 3: 0.85, 2: 0.70, 1: 0.55}
BASELINE_BUDGET = 120
BUDGET_TOLERANCE = 0.10
HARD_DIFFICULTY_MULTIPLIER = 1.15

# generator-prompt.md ROOM_CAP: total monsters allowed in one room.
ROOM_CAP_BY_HERO_COUNT = {4: 4, 3: 3, 2: 3, 1: 2}

# generator-prompt.md MIN_DEPTH: door-hops from stairway room to objective room.
MIN_DEPTH_BY_SIZE = {"short": 3, "full": 5}

# WANDERING_CONSTRAINT: for 1-2 heroes, wandering monster cost <= fimir.
WANDERING_MAX_COST_LOW_HERO_COUNT = 8

DOOR_TOTAL_CAP = 21
CORRIDOR_TRAP_CAP = 3
ROOM_TRAP_CAP = 1

# Blocked-square tiles in the owner's box: 8 that cover one square, 2
# that cover two adjacent squares. They don't recycle (a tile stays on
# the board once placed), so 12 squares is the hard ceiling -- and the
# last 4 of those only exist as adjacent pairs.
# What a Chaos spell adds to its carrier's threat cost. Measured, not
# guessed (sim/results/2026-08-chaos-spells.md): a boss holding the three
# harshest cards costs the party +0.5 Body Points per quest, which the
# budget sweep prices at about 3.5% of budget -- and only ~0.5 of three
# assigned cards ever gets spent, because bosses die before they cast.
# 2 points per spell rounds that up rather than down.
CHAOS_SPELL_THREAT_COST = 2

# How many monsters in one quest may carry Chaos spells. The quest book
# hands them to the villain and at most a lieutenant -- never to the
# rank and file -- and a dungeon with four casters in it reads as a
# different game.
MAX_SPELL_CASTERS = 2

BLOCKED_SINGLE_TILES = 8
BLOCKED_DOUBLE_TILES = 2
BLOCKED_SQUARE_CAP = BLOCKED_SINGLE_TILES + 2 * BLOCKED_DOUBLE_TILES


def caster_types(catalogs) -> list[str]:
    """Monster types that may carry Chaos spells at all.

    The owner's box has three figures worth arming -- 4 chaos warriors,
    1 chaos warlock, 1 gargoyle -- and the cards go to those. Never an
    orc in the crowd, never the shambling undead. Marked with
    "caster": true in data/monsters.json so the list lives with the
    stats rather than in a constant here.
    """
    return sorted(name for name, entry in catalogs.monsters.items() if entry.get("caster"))


def _has_disjoint_pairs(pairs: list, count: int) -> bool:
    """Can `count` of these pairs be chosen without sharing a square?
    Brute force is fine: count is at most BLOCKED_DOUBLE_TILES (2).
    """
    if count <= 0:
        return True
    for i, pair in enumerate(pairs):
        rest = [p for p in pairs[i + 1:] if p.isdisjoint(pair)]
        if _has_disjoint_pairs(rest, count - 1):
            return True
    return False


def blocked_squares_fit_tiles(squares) -> bool:
    """True if the owner can actually lay these squares out with the
    tiles in the box. Past 8 squares the double tiles have to carry the
    rest, and a double tile only covers two ADJACENT squares -- so 12
    scattered singles don't fit even though 12 is the cap.
    """
    cells = {tuple(sq) for sq in squares}
    if len(cells) > BLOCKED_SQUARE_CAP:
        return False
    doubles_needed = -(-(len(cells) - BLOCKED_SINGLE_TILES) // 2)
    if doubles_needed <= 0:
        return True
    if doubles_needed > BLOCKED_DOUBLE_TILES:
        return False
    pairs = [
        frozenset((a, b))
        for a in cells
        for b in ((a[0] + 1, a[1]), (a[0], a[1] + 1))
        if b in cells
    ]
    return _has_disjoint_pairs(pairs, doubles_needed)


def _monster_threat_cost(monster: dict, catalog_entry: dict) -> int:
    """Base threat cost, plus extra threat from stat overrides and any
    Chaos spells the monster carries.

    generator-prompt.md: "overrides add its extra threat: +1 per added
    body or attack die" — only increases to attack/body count (a weaker
    override isn't a discount; defend/mind/move overrides don't affect
    cost). This is the documented cost model, not an inference.
    """
    cost = catalog_entry["threatCost"]
    overrides = monster.get("overrides", {})
    for stat in ("attack", "body"):
        if stat in overrides:
            cost += max(0, overrides[stat] - catalog_entry[stat])
    # A carried Chaos card is threat the base formula can't see.
    cost += CHAOS_SPELL_THREAT_COST * len(monster.get("spells") or [])
    return cost


def _room_area_graph(catalogs: Catalogs, quest: dict) -> dict:
    """area -> set of areas reachable by exactly one non-secret door."""
    board = catalogs.board
    graph: dict = {}
    for edge in _door_edges(quest, NON_SECRET_STATES):
        a, b = tuple(edge)
        area_a, area_b = board.area_of.get(a), board.area_of.get(b)
        if area_a is None or area_b is None or area_a == area_b:
            continue
        graph.setdefault(area_a, set()).add(area_b)
        graph.setdefault(area_b, set()).add(area_a)
    return graph


def _door_hop_depth(catalogs: Catalogs, quest: dict, start_room: str, target_room: str):
    graph = _room_area_graph(catalogs, quest)
    if start_room == target_room:
        return 0
    seen = {start_room}
    q = deque([(start_room, 0)])
    while q:
        area, depth = q.popleft()
        for n in graph.get(area, ()):
            if n in seen:
                continue
            if n == target_room:
                return depth + 1
            seen.add(n)
            q.append((n, depth + 1))
    return None  # unreachable via primary doors; reachability check reports this


def check_balance(quest: dict, params: dict, catalogs: Catalogs) -> list:
    errors = []
    hero_count = params["heroCount"]
    difficulty = params.get("difficulty", "standard")
    size = params.get("size", "full")

    quest_rooms = quest.get("rooms", {})

    # -- monster budget + per-room caps --
    total_cost = 0
    for room_id, room in quest_rooms.items():
        monsters = room.get("monsters", [])
        type_counts = Counter(m.get("type") for m in monsters)
        for mtype, count in type_counts.items():
            entry = catalogs.monsters.get(mtype)
            if entry is None:
                continue  # geometry check already reported unknown type
            room_cap = entry["roomCap"]
            if count > room_cap:
                errors.append(
                    f"{room_id} has {count} {mtype}(s), exceeding the owned-mini cap of {room_cap}"
                )

        room_cap_total = ROOM_CAP_BY_HERO_COUNT[hero_count]
        if len(monsters) > room_cap_total:
            errors.append(
                f"{room_id} has {len(monsters)} monsters, exceeding the "
                f"{hero_count}-hero per-room cap of {room_cap_total}"
            )

        for m in monsters:
            entry = catalogs.monsters.get(m.get("type"))
            if entry is not None:
                total_cost += _monster_threat_cost(m, entry)

    ratio = HERO_BUDGET_RATIO[hero_count]
    target = BASELINE_BUDGET * ratio
    if difficulty == "hard":
        target *= HARD_DIFFICULTY_MULTIPLIER
    low, high = target * (1 - BUDGET_TOLERANCE), target * (1 + BUDGET_TOLERANCE)
    if not (low <= total_cost <= high):
        errors.append(
            f"monster budget is {total_cost}, outside the {hero_count}-hero "
            f"{difficulty} target range {low:.0f}-{high:.0f} (target {target:.0f})"
        )

    # -- boss/objective depth --
    stair_room = quest.get("stairway", {}).get("room")
    objective_room = _objective_target_room(quest, catalogs.board)
    if stair_room in catalogs.board.room_squares and objective_room in catalogs.board.room_squares:
        min_depth = MIN_DEPTH_BY_SIZE.get(size, MIN_DEPTH_BY_SIZE["full"])
        depth = _door_hop_depth(catalogs, quest, stair_room, objective_room)
        if depth is not None and depth < min_depth:
            if depth <= 1:
                errors.append(
                    f"objective room {objective_room} is adjacent to the stairway room {stair_room} "
                    f"(must be at least {min_depth} doors deep)"
                )
            else:
                errors.append(
                    f"objective room {objective_room} is only {depth} door(s) from the stairway "
                    f"room {stair_room}, needs at least {min_depth}"
                )

    # -- traps --
    for room_id, room in quest_rooms.items():
        traps = room.get("traps", [])
        if len(traps) > ROOM_TRAP_CAP:
            errors.append(f"{room_id} has {len(traps)} traps, exceeding the cap of {ROOM_TRAP_CAP} per room")

    corridor_traps = quest.get("corridorTraps", [])
    if len(corridor_traps) > CORRIDOR_TRAP_CAP:
        errors.append(
            f"quest has {len(corridor_traps)} corridor traps, exceeding the cap of {CORRIDOR_TRAP_CAP}"
        )

    # -- wandering monster --
    wandering = quest.get("wanderingMonster")
    if wandering not in catalogs.monsters:
        errors.append(f"wanderingMonster '{wandering}' is not a known monster type")
    elif hero_count <= 2:
        cost = catalogs.monsters[wandering]["threatCost"]
        if cost > WANDERING_MAX_COST_LOW_HERO_COUNT:
            errors.append(
                f"wanderingMonster '{wandering}' costs {cost}, exceeding the "
                f"{WANDERING_MAX_COST_LOW_HERO_COUNT}-cost cap for {hero_count}-hero quests"
            )

    # -- furniture owned-piece caps (whole quest, furniture doesn't recycle) --
    furniture_counts = Counter()
    for room in quest_rooms.values():
        for f in room.get("furniture", []):
            furniture_counts[f.get("type")] += 1
    for ftype, count in furniture_counts.items():
        entry = catalogs.furniture.get(ftype)
        if entry is None:
            continue  # geometry check already reported unknown type
        if count > entry["owned"]:
            errors.append(f"quest uses {count} '{ftype}' pieces, exceeding the owned count of {entry['owned']}")

    # -- Chaos spell cards (physical: one of each in the box) --
    assigned: Counter = Counter()
    casters: list[str] = []
    for room_id, room in quest_rooms.items():
        for monster in room.get("monsters", []):
            spells = monster.get("spells") or []
            if spells:
                casters.append(monster.get("id", "?"))
            if spells and not monster.get("name"):
                errors.append(
                    f"monster {monster.get('id', '?')} in {room_id} carries Chaos spells but has no name -- "
                    f"the cards go to \"specific monsters called for in the Quest notes\""
                )
            if spells and monster.get("type") not in set(caster_types(catalogs)):
                errors.append(
                    f"a {monster.get('type')} can't carry Chaos spells -- only "
                    f"{', '.join(caster_types(catalogs))} cast in the quest book"
                )
            for spell_id in spells:
                if spell_id not in CHAOS_SPELLS:
                    errors.append(f"monster {monster.get('id', '?')} carries unknown Chaos spell '{spell_id}'")
                    continue
                assigned[spell_id] += 1
                if CHAOS_SPELLS[spell_id].get("requiresEscapeDestination") and not quest.get("escapeDestination"):
                    errors.append(
                        f"{CHAOS_SPELLS[spell_id]['name']} needs quest.escapeDestination -- "
                        f"the card teleports its caster to a place marked on the map"
                    )
    if len(casters) > MAX_SPELL_CASTERS:
        errors.append(
            f"{len(casters)} monsters carry Chaos spells ({', '.join(sorted(casters))}), more than the "
            f"{MAX_SPELL_CASTERS} the quest book ever arms -- spells go to the villain and a lieutenant, "
            f"not to the rank and file"
        )

    for spell_id, count in assigned.items():
        if count > 1:
            errors.append(
                f"Chaos spell '{spell_id}' is given to {count} monsters, but there is one physical card of each"
            )

    # -- blocked square tiles (physical, don't recycle) --
    blocked = [
        tuple(sq) for sq in quest.get("blockedSquares", [])
        if isinstance(sq, (list, tuple)) and len(sq) == 2
    ]
    if len(set(blocked)) > BLOCKED_SQUARE_CAP:
        errors.append(
            f"quest declares {len(set(blocked))} blocked squares, more than the "
            f"{BLOCKED_SQUARE_CAP} squares the owned tiles cover "
            f"({BLOCKED_SINGLE_TILES} single + {BLOCKED_DOUBLE_TILES} double)"
        )
    elif not blocked_squares_fit_tiles(blocked):
        errors.append(
            f"the {len(set(blocked))} blocked squares can't be laid out with "
            f"{BLOCKED_SINGLE_TILES} single + {BLOCKED_DOUBLE_TILES} double tiles "
            f"(past {BLOCKED_SINGLE_TILES} squares the rest must come in adjacent pairs)"
        )

    # -- door physical caps --
    doors = quest.get("doors", [])
    if len(doors) > DOOR_TOTAL_CAP:
        errors.append(f"quest declares {len(doors)} doors, exceeding the owned count of {DOOR_TOTAL_CAP}")
    # No per-state cap: every door starts closed in play regardless of
    # the state declared here, and the closed piece is recycled the
    # moment Zargon swaps it for an open one, so "how many are closed"
    # constrains nothing physical.

    return errors
