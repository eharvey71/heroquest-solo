"""Turn-type roller (the digital Zargon Deck) and target selection.

Weights are CLAUDE.md's Balance system table verbatim. Hard difficulty's
"+1 extra wandering-monster weight point" is taken from `normal` to keep
the total at 100 -- the doc doesn't say which bucket it comes from, but
normal is the only one large enough that -1 doesn't materially change
its character.

Cunning-turn targeting ("focus-fire lowest-threat-to-kill hero") can't
be computed here: hero body points are physical-only, permanently out
of scope for this app (see CLAUDE.md's physical/digital boundary). This
module stays pure/deterministic by taking the answer as a parameter --
the caller is responsible for asking the human at the table, and only
needs to ask at all when there's more than one hero to choose from.
"""

from __future__ import annotations

import random
from collections import deque

from validator.catalogs import Board

from .movement import Coord, find_path, squares_adjacent_to

TURN_WEIGHTS_BY_HERO_COUNT = {
    4: {"normal": 72, "cunning": 24, "wandering": 4},
    3: {"normal": 76, "cunning": 20, "wandering": 4},
    2: {"normal": 80, "cunning": 16, "wandering": 4},
    1: {"normal": 84, "cunning": 12, "wandering": 4},
}


def turn_type_weights(hero_count: int, difficulty: str = "standard") -> dict[str, int]:
    weights = dict(TURN_WEIGHTS_BY_HERO_COUNT[hero_count])
    if difficulty == "hard":
        weights["wandering"] += 1
        weights["normal"] -= 1
    return weights


def roll_turn_type(hero_count: int, difficulty: str = "standard", rng: random.Random | None = None) -> str:
    rng = rng or random
    weights = turn_type_weights(hero_count, difficulty)
    types = list(weights.keys())
    counts = list(weights.values())
    return rng.choices(types, weights=counts, k=1)[0]


def select_normal_target(
    board: Board,
    revealed: set[Coord],
    door_edges: set[frozenset],
    occupied: set[Coord],
    monster_pos: Coord,
    heroes: list[dict],
) -> str | None:
    """Nearest hero by path distance (through revealed squares + open
    doors). Returns the hero's id, or None if no hero is reachable at
    all this turn (e.g. everything revealed so far is walled off).
    """
    best_id: str | None = None
    best_len: int | None = None
    for hero in heroes:
        goals = squares_adjacent_to(tuple(hero["pos"]))
        path = find_path(board, revealed, door_edges, occupied, monster_pos, goals)
        if path is None:
            continue
        length = len(path) - 1
        if best_len is None or length < best_len:
            best_len = length
            best_id = hero["id"]
    return best_id


def needs_cunning_target_prompt(heroes: list[dict]) -> bool:
    """Only worth asking a human when there's an actual choice to make."""
    return len(heroes) > 1


def select_cunning_target(heroes: list[dict], lowest_bp_hero_id: str | None) -> str:
    """`lowest_bp_hero_id`: the human's answer to "which hero is lowest
    on BP?" -- required whenever needs_cunning_target_prompt() is True.
    With a single hero in play there's nothing to ask; that hero is the
    target regardless of what's passed in.
    """
    if len(heroes) == 1:
        return heroes[0]["id"]
    if lowest_bp_hero_id is None:
        raise ValueError("lowest_bp_hero_id is required when more than one hero is in play")
    if not any(h["id"] == lowest_bp_hero_id for h in heroes):
        raise ValueError(f"lowest_bp_hero_id '{lowest_bp_hero_id}' is not one of the heroes in play")
    return lowest_bp_hero_id


def should_guard(monster_room_id: str, objective_room_id: str) -> bool:
    """A monster stationed in the objective's own room holds position on
    a cunning turn rather than chasing -- "guard objectives" per
    CLAUDE.md. The caller checks guard_should_engage() before invoking
    movement to decide whether this guard has actually noticed anyone
    yet.
    """
    return monster_room_id == objective_room_id


def guard_should_engage(
    board: Board,
    monster_room_id: str,
    door_edges: set[frozenset],
    heroes: list[dict],
) -> bool:
    """A guard wakes when a hero is IN its room, or standing right at an
    open doorway into it (can see in, even without stepping inside) --
    not merely "adjacent to the monster's exact square". That narrower
    trigger let a hero walk into a large room, search it, and loot
    around a statue that only "woke" once someone bumped its square.
    Plain grid adjacency across a wall (no door there) intentionally
    does NOT count -- that's not a sightline, just two squares that
    happen to share an edge on the grid.
    """
    for hero in heroes:
        hero_pos = tuple(hero["pos"])
        if board.area_of.get(hero_pos) == monster_room_id:
            return True
        for edge in door_edges:
            a, b = tuple(edge)
            if hero_pos not in (a, b):
                continue
            other = b if hero_pos == a else a
            if board.area_of.get(other) == monster_room_id:
                return True
    return False


def _nearest_free_square(board: Board, start: Coord, occupied: set[Coord]) -> Coord | None:
    """BFS ring expansion for "nearest free square if boxed in" -- plain
    grid adjacency, no door/reveal gating, since this is about finding
    physical table space next to a hero already standing in a room, not
    about pathing anywhere.
    """
    if board.area_of.get(start) is not None and start not in occupied:
        return start
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n in seen:
                continue
            seen.add(n)
            if board.area_of.get(n) is None:
                continue
            if n not in occupied:
                return n
            queue.append(n)
    return None


def _placement_instruction(monster_type: str, pos: Coord) -> str:
    return f"Place the {monster_type} mini at square [{pos[0]},{pos[1]}]."


def spawn_wandering_monster_from_treasure_card(
    board: Board,
    monster_type: str,
    searcher_pos: Coord,
    occupied: set[Coord],
) -> dict | None:
    """The treasure-deck wandering monster card, drawn during a search
    (the physical "wandering monster?" button). This is rulebook-
    mandated, not a design choice: the 1989 NA rules place it adjacent
    to the searching hero and it attacks immediately. Falls back to the
    nearest free square if every adjacent square is occupied.
    """
    if not monster_type:
        return None

    candidates = sorted(
        (c for c in squares_adjacent_to(searcher_pos) if board.area_of.get(c) is not None and c not in occupied),
        key=lambda c: (c[1], c[0]),  # deterministic tie-break, not a rules requirement
    )
    spawn_pos = candidates[0] if candidates else _nearest_free_square(board, searcher_pos, occupied)
    if spawn_pos is None:
        return None

    return {
        "type": monster_type,
        "pos": spawn_pos,
        "attacksImmediately": True,
        "placementInstruction": _placement_instruction(monster_type, spawn_pos),
    }


def _frontier_squares(board: Board, revealed: set[Coord], quest_doors: list[dict]) -> set[Coord]:
    """Revealed squares that border unrevealed territory -- either across
    an open stretch of corridor, or across a declared door -- i.e. the
    edge of what the party has actually explored. A revealed square
    bordering an unrevealed square with NO connection between them
    (a plain wall, no door) doesn't count; that's not an edge the party
    could be approached from.
    """
    door_squares_by_edge = {
        frozenset((tuple(d["squares"][0]), tuple(d["squares"][1])))
        for d in quest_doors
        if len(d.get("squares", [])) == 2
    }

    frontier: set[Coord] = set()
    for sq in revealed:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (sq[0] + dx, sq[1] + dy)
            if board.area_of.get(n) is None or n in revealed:
                continue
            same_area = board.area_of.get(n) == board.area_of.get(sq)
            connected = same_area or frozenset((sq, n)) in door_squares_by_edge
            if connected:
                frontier.add(sq)
                break
    return frontier


def spawn_wandering_monster_from_turn_roll(
    board: Board,
    quest: dict,
    revealed: set[Coord],
    quest_doors: list[dict],
    occupied: set[Coord],
    heroes: list[dict],
) -> dict | None:
    """The Zargon Deck's `wandering` turn type (no searcher involved).
    Spawning at the stairway is defensible but weak late in a quest --
    it lands far behind cleared territory and spends several turns just
    walking. Spawns at the nearest unrevealed doorway/corridor edge to
    the party instead (real pressure, not a foot-race), falling back to
    the stairway only when no frontier exists yet (e.g. turn 1).
    """
    monster_type = quest.get("wanderingMonster")
    if not monster_type:
        return None

    frontier = _frontier_squares(board, revealed, quest_doors)
    frontier -= occupied

    spawn_pos: Coord | None = None
    if frontier and heroes:
        hero_positions = [tuple(h["pos"]) for h in heroes]

        def nearest_hero_distance(sq: Coord) -> int:
            return min(abs(sq[0] - hp[0]) + abs(sq[1] - hp[1]) for hp in hero_positions)

        spawn_pos = min(frontier, key=lambda sq: (nearest_hero_distance(sq), sq[1], sq[0]))
    elif frontier:
        spawn_pos = min(frontier, key=lambda sq: (sq[1], sq[0]))

    if spawn_pos is None:
        stairway = quest.get("stairway", {})
        pos = stairway.get("pos")
        if not pos:
            return None
        spawn_pos = _nearest_free_square(board, tuple(pos), occupied) or tuple(pos)

    return {
        "type": monster_type,
        "pos": spawn_pos,
        "attacksImmediately": False,
        "placementInstruction": _placement_instruction(monster_type, spawn_pos),
    }
