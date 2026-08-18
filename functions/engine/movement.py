"""A* monster movement on the revealed map.

Per CLAUDE.md: "movement (A* on revealed map)" -- a monster can only
path through squares the party has already revealed (Zargon doesn't
send monsters wandering through walls/unopened doors into rooms no one
has found yet), and only through doors that are currently open or
closed (not locked/secret -- those need a key or a search, which is a
hero action). All other tokens (hero or monster) are hard obstacles;
HeroQuest's "heroes may pass through fellow heroes" exception (CLAUDE.md
rules edition note) is stated for hero movement specifically and does
not extend to monsters here -- a documented assumption, not the
official rulebook's exact wording on monster movement.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from validator.catalogs import Board

Coord = tuple[int, int]

_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def revealed_squares(board: Board, revealed: dict) -> set[Coord]:
    """revealed: {"rooms": [...], "corridorSquares": [[x,y],...]} -- the
    game state shape from quest-schema.md section 4.
    """
    squares: set[Coord] = set()
    for room_id in revealed.get("rooms", []):
        squares.update(board.room_squares.get(room_id, ()))
    for sq in revealed.get("corridorSquares", []):
        squares.add(tuple(sq))
    return squares


def passable_door_edges(quest_doors: list[dict], door_states: dict) -> set[frozenset]:
    """quest_doors: the quest's static door declarations. door_states:
    the game state's current per-door status ({"D1": "open"}),
    overriding the quest's initially-declared state once a door has
    been opened/found during play.
    """
    edges = set()
    for d in quest_doors:
        door_id = d.get("id")
        state = door_states.get(door_id, d.get("state"))
        if state not in ("open", "closed"):
            continue
        squares = d.get("squares", [])
        if len(squares) != 2:
            continue
        edges.add(frozenset((tuple(squares[0]), tuple(squares[1]))))
    return edges


def squares_adjacent_to(coord: Coord) -> set[Coord]:
    return {(coord[0] + dx, coord[1] + dy) for dx, dy in _STEPS}


def _neighbors(coord: Coord, board: Board, revealed: set[Coord], door_edges: set[frozenset], occupied: set[Coord]):
    area = board.area_of.get(coord)
    for dx, dy in _STEPS:
        n = (coord[0] + dx, coord[1] + dy)
        if n in occupied or n not in revealed:
            continue
        n_area = board.area_of.get(n)
        if n_area is None:
            continue
        if n_area == area or frozenset((coord, n)) in door_edges:
            yield n


def _manhattan(a: Coord, b: Coord) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def find_path(
    board: Board,
    revealed: set[Coord],
    door_edges: set[frozenset],
    occupied: set[Coord],
    start: Coord,
    goals: set[Coord],
) -> list[Coord] | None:
    """A* shortest path from `start` to the nearest square in `goals`
    (plural: any one of them satisfies the search -- used to path to
    "any square adjacent to the target", not one fixed destination).
    Returns the full path including `start`, or None if unreachable.
    `occupied` need not exclude `start`; that's handled here.
    """
    occupied = occupied - {start}
    if not goals:
        return None
    if start in goals:
        return [start]

    def h(c: Coord) -> int:
        return min(_manhattan(c, g) for g in goals)

    open_heap: list[tuple[int, int, Coord]] = [(h(start), 0, start)]
    came_from: dict[Coord, Coord] = {}
    g_score: dict[Coord, int] = {start: 0}
    visited: set[Coord] = set()

    while open_heap:
        _, cost, current = heapq.heappop(open_heap)
        if current in visited:
            continue
        visited.add(current)

        if current in goals:
            path = [current]
            while path[-1] != start:
                path.append(came_from[path[-1]])
            path.reverse()
            return path

        for neighbor in _neighbors(current, board, revealed, door_edges, occupied):
            tentative = cost + 1
            if tentative < g_score.get(neighbor, float("inf")):
                g_score[neighbor] = tentative
                came_from[neighbor] = current
                heapq.heappush(open_heap, (tentative + h(neighbor), tentative, neighbor))

    return None


@dataclass
class MoveResult:
    path: list[Coord]  # full shortest path to the nearest goal, including the start square
    reachable_this_turn: list[Coord]  # path truncated to move_points, including the start square
    reached_target_adjacency: bool  # True if the monster ends adjacent to the target this turn


def move_toward(
    board: Board,
    revealed: set[Coord],
    door_edges: set[frozenset],
    occupied: set[Coord],
    start: Coord,
    target: Coord,
    move_points: int,
) -> MoveResult | None:
    """Shortest path from `start` to a square adjacent to `target`
    (monsters attack from an adjacent square, they don't move onto the
    target's own square), truncated to how far the monster can actually
    get this turn. Returns None if no adjacent square is reachable at
    all (e.g. the target is fully walled off from revealed territory).
    """
    goals = {g for g in squares_adjacent_to(target) if g not in occupied and board.area_of.get(g) is not None}
    path = find_path(board, revealed, door_edges, occupied, start, goals)
    if path is None:
        return None

    steps = min(move_points, len(path) - 1)
    reachable = path[: steps + 1]
    reached_adjacency = reachable[-1] in squares_adjacent_to(target)

    return MoveResult(path=path, reachable_this_turn=reachable, reached_target_adjacency=reached_adjacency)
