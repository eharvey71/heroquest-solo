"""Line of sight -- the rulebook's "SEE" (1989 rulebook page 15).

    "Heroes and monsters are only visible if an unobstructed straight
    line can be traced from the spellcaster to the target. Draw an
    invisible straight line between the center of the square the
    spellcaster is on and the center of the square the target is on. If
    the line does not cross a wall, closed door, Hero or monster, the
    target is declared visible, even if the line just touches a corner
    or wall edge."

Two callers with deliberately different blocker sets:

- TARGETING (which monsters a hero can see, and later spell targets)
  applies the rule strictly: walls, closed doors, and figures all
  block.
- REVEALING (what fog of war uncovers when a hero looks down a
  corridor) ignores figures. Terrain that has been seen stays seen;
  letting a hero shuffle sideways and un-reveal a corridor would be
  both wrong and maddening to play against. Walls and closed doors
  still block, so the party never sees around a corner.

The "touches a corner" clause is honoured where sight could actually
pass -- a diagonal graze is allowed only if at least one way round the
corner is open. Permitting every diagonal instead let a line escape a
sealed room between two wall corners.
"""

from __future__ import annotations

from validator.catalogs import CORRIDOR, Board

Coord = tuple[int, int]

# Fine enough that no cell along a board-length line is skipped (the
# board is 26x19, so the longest sight line is ~32 cells).
_SAMPLES_PER_CELL = 64


def _cells_along(a: Coord, b: Coord) -> list[Coord]:
    """Ordered, de-duplicated cells the centre-to-centre segment passes
    through, including both endpoints.
    """
    ax, ay = a[0] + 0.5, a[1] + 0.5
    bx, by = b[0] + 0.5, b[1] + 0.5
    steps = max(1, int(max(abs(bx - ax), abs(by - ay)) * _SAMPLES_PER_CELL))

    cells: list[Coord] = []
    for i in range(steps + 1):
        t = i / steps
        cell = (int(ax + (bx - ax) * t), int(ay + (by - ay) * t))
        if not cells or cells[-1] != cell:
            cells.append(cell)
    return cells


def _edge_open(board: Board, a: Coord, b: Coord, open_door_edges: set[frozenset]) -> bool:
    """Can sight cross the edge between two orthogonally-adjacent cells?
    Same-area edges are open floor; anything else needs an open door.
    """
    area_a, area_b = board.area_of.get(a), board.area_of.get(b)
    if area_a is None or area_b is None:
        return False
    if area_a == area_b:
        return True
    return frozenset((a, b)) in open_door_edges


def has_line_of_sight(
    board: Board,
    origin: Coord,
    target: Coord,
    *,
    open_door_edges: set[frozenset],
    walls: frozenset[Coord] = frozenset(),
    figures: frozenset[Coord] = frozenset(),
) -> bool:
    """`walls`: squares that block sight outright (blocked-square tiles,
    collapsed ceilings). `figures`: hero/monster squares -- pass an empty
    set when revealing terrain, the real set when targeting. Neither
    endpoint ever blocks itself.
    """
    if origin == target:
        return True

    cells = _cells_along(origin, target)
    for i, cell in enumerate(cells):
        if board.area_of.get(cell) is None:
            return False
        is_endpoint = i == 0 or i == len(cells) - 1
        if not is_endpoint and (cell in walls or cell in figures):
            return False

        if i == 0:
            continue
        prev = cells[i - 1]
        dx, dy = abs(cell[0] - prev[0]), abs(cell[1] - prev[1])
        if dx + dy != 1:
            # A diagonal step grazes a corner. The rulebook's "even if
            # the line just touches a corner" makes that visible only
            # where sight could actually pass: if BOTH ways round the
            # corner are walled, the line is squeezing between two walls
            # (e.g. out of a sealed room) and is blocked.
            if not any(
                _edge_open(board, prev, mid, open_door_edges) and _edge_open(board, mid, cell, open_door_edges)
                for mid in ((prev[0], cell[1]), (cell[0], prev[1]))
            ):
                return False
            continue
        # An orthogonal step between two areas needs an OPEN door on that
        # exact edge; otherwise it is a wall or an unopened door.
        if not _edge_open(board, prev, cell, open_door_edges):
            return False
    return True


def visible_corridor_squares(
    board: Board,
    origin: Coord,
    *,
    open_door_edges: set[frozenset],
    walls: frozenset[Coord] = frozenset(),
) -> set[Coord]:
    """Corridor squares a hero standing on `origin` can see.

    Rooms are deliberately excluded: the rulebook reveals a room's
    contents when its door is OPENED (engine/doors.py), not by peering
    in, so room fog stays door-gated and this only handles the "look
    down a corridor" case.
    """
    seen: set[Coord] = set()
    for square in board.corridor_squares:
        if has_line_of_sight(
            board, origin, square, open_door_edges=open_door_edges, walls=walls, figures=frozenset()
        ):
            seen.add(square)
    if board.area_of.get(origin) == CORRIDOR:
        seen.add(origin)
    return seen
