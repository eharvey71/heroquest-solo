"""BFS reachability from the stairway, through declared doors and the
open corridor network. Corresponds to design/quest-generator-design.md
section 5 "Reachability".

Model: every board square is a graph node. Two orthogonally-adjacent
squares are connected if they're in the same area (a room's interior is
always open, and corridor is one open network per board.json) or if a
door sits on that exact edge. blockedSquares and furniture squares are removed from the
graph entirely (furniture is impassable -- see geometry.furniture_squares). Secret doors are excluded from the "primary" graph (the one a
party can reliably walk without searching) but included in the "full"
graph, matching the design doc's distinction for objective reachability.
"""

from __future__ import annotations

from collections import deque

from .catalogs import Catalogs
from .geometry import footprint_cells, furniture_squares

NON_SECRET_STATES = {"open", "closed", "locked"}


def _door_edges(quest: dict, allowed_states) -> set:
    edges = set()
    for d in quest.get("doors", []):
        squares = d.get("squares", [])
        if len(squares) != 2:
            continue
        if d.get("state") not in allowed_states:
            continue
        a, b = tuple(squares[0]), tuple(squares[1])
        edges.add(frozenset((a, b)))
    return edges


def _bfs(board, start_cells, door_edges, blocked):
    seen = set(c for c in start_cells if c not in blocked)
    q = deque(seen)
    while q:
        x, y = q.popleft()
        area = board.area_of.get((x, y))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n in seen or n in blocked or n not in board.area_of:
                continue
            n_area = board.area_of[n]
            traversable = n_area == area or frozenset(((x, y), n)) in door_edges
            if traversable:
                seen.add(n)
                q.append(n)
    return seen


def _objective_target_room(quest: dict, board) -> str | None:
    target = quest.get("objective", {}).get("target", {})
    if "room" in target:
        return target["room"]
    monster_id = target.get("monsterId")
    if monster_id is None:
        return None
    for room_id, room in quest.get("rooms", {}).items():
        for m in room.get("monsters", []):
            if m.get("id") == monster_id:
                return room_id
    return None


def check_reachability(quest: dict, catalogs: Catalogs) -> list:
    board = catalogs.board
    errors = []

    stairway = quest.get("stairway", {})
    stair_room = stairway.get("room")
    if stair_room not in board.room_squares or "pos" not in stairway:
        return errors  # geometry check already reported this

    start_cells = footprint_cells(stairway["pos"], (2, 2))
    blocked = frozenset(tuple(s) for s in quest.get("blockedSquares", [])) | furniture_squares(quest, catalogs)

    primary_edges = _door_edges(quest, NON_SECRET_STATES)
    full_edges = _door_edges(quest, NON_SECRET_STATES | {"secret"})

    reached_full = _bfs(board, start_cells, full_edges, blocked)

    populated_rooms = [rid for rid, room in quest.get("rooms", {}).items() if rid in board.room_squares]
    for room_id in populated_rooms:
        if not (board.room_squares[room_id] & reached_full):
            errors.append(f"{room_id} is unreachable from the stairway (no door path, even including secret doors)")

    objective_room = _objective_target_room(quest, board)
    if objective_room is not None and objective_room in board.room_squares:
        if not (board.room_squares[objective_room] & reached_full):
            errors.append(f"objective room {objective_room} is unreachable from the stairway")
        else:
            reached_primary = _bfs(board, start_cells, primary_edges, blocked)
            objective_on_primary_path = bool(board.room_squares[objective_room] & reached_primary)
            if not objective_on_primary_path:
                hint = quest.get("objective", {}).get("secretPathHint")
                hint_room = hint.get("room") if hint else None
                hint_room_on_primary_path = (
                    hint_room in board.room_squares and bool(board.room_squares[hint_room] & reached_primary)
                )
                if not hint or not hint_room_on_primary_path:
                    errors.append(
                        f"objective room {objective_room} is only reachable through a secret door, "
                        f"but objective.secretPathHint is missing or points to an unreachable room "
                        f"(a hint must exist in a room reachable without secret doors)"
                    )

    return errors
