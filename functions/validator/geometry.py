"""Geometry checks: catalog references, positions, footprints, overlaps,
door wall-edges, stairway placement.

Corresponds to design/quest-generator-design.md section 5 "Geometry".
"""

from __future__ import annotations

from .catalogs import Catalogs
from .result import fmt_pos

ORIENTATIONS = {"N", "S", "E", "W"}


def footprint_cells(pos, footprint, orientation="N"):
    """Cells occupied by a w x h piece anchored at pos (top-left corner).

    E/W orientation swaps width and height; N/S use the footprint as-is.
    This is a documented assumption (the schema doesn't pin it down):
    furniture/stairway footprints are simple axis-aligned rectangles, no
    partial rotation beyond the 90-degree swap.
    """
    w, h = footprint
    if orientation in ("E", "W"):
        w, h = h, w
    x0, y0 = pos
    return [(x0 + dx, y0 + dy) for dx in range(w) for dy in range(h)]


def furniture_squares(quest: dict, catalogs) -> set:
    """Every board square a furniture piece stands on.

    Furniture is impassable -- heroes and monsters walk around it, never
    over it -- so the same set feeds movement resolution (engine) and the
    reachability BFS: a piece parked across a doorway would otherwise
    seal off a room the validator still believes is reachable.
    """
    cells = set()
    for room in quest.get("rooms", {}).values():
        for f in room.get("furniture", []):
            entry = catalogs.furniture.get(f.get("type"))
            if entry is None or f.get("pos") is None:
                continue
            cells.update(footprint_cells(tuple(f["pos"]), entry["footprint"], f.get("orientation", "N")))
    return cells


def check_geometry(quest: dict, catalogs: Catalogs) -> list:
    board = catalogs.board
    errors = []
    occupied = {}  # (x, y) -> label of first occupant, for overlap detection

    def claim(cells, label):
        for c in cells:
            prior = occupied.get(c)
            if prior is not None:
                errors.append(
                    f"{label} at {fmt_pos(c)} overlaps {prior} (square already occupied)"
                )
            else:
                occupied[c] = label

    def require_in_room(label, pos, room_id):
        pos = tuple(pos)
        if room_id not in board.room_squares:
            return  # already reported as unknown room id below
        if pos not in board.room_squares[room_id]:
            errors.append(f"{label} at {fmt_pos(pos)} is outside {room_id}")

    def pos_of(entity, label):
        """Extracts a (x, y) tuple, or None + an error if pos is missing
        or malformed. Guards against crashing on malformed LLM output."""
        pos = entity.get("pos")
        if not (isinstance(pos, (list, tuple)) and len(pos) == 2):
            errors.append(f"{label} has a missing or malformed 'pos'")
            return None
        return tuple(pos)

    quest_rooms = quest.get("rooms", {})

    # -- room ids referenced actually exist --
    for room_id in quest_rooms:
        if room_id not in board.room_squares:
            errors.append(f"room {room_id} does not exist on the board")

    stairway = quest.get("stairway", {})
    if not stairway:
        errors.append("quest is missing a stairway")
    stair_room = stairway.get("room")
    if stair_room is not None and stair_room not in board.room_squares:
        errors.append(f"stairway room {stair_room} does not exist on the board")

    # -- stairway: 2x2 footprint, fully inside its room, no overlap --
    stair_pos = pos_of(stairway, "stairway") if stairway else None
    if stair_room in board.room_squares and stair_pos is not None:
        cells = footprint_cells(stair_pos, (2, 2))
        for c in cells:
            if c not in board.room_squares[stair_room]:
                errors.append(
                    f"stairway at {fmt_pos(stair_pos)} is outside {stair_room} "
                    f"(2x2 footprint doesn't fit)"
                )
        claim(cells, "stairway")

    # -- per-room entities: monsters, furniture, traps --
    for room_id, room in quest_rooms.items():
        if room_id not in board.room_squares:
            continue  # already reported; avoid cascading noise

        for m in room.get("monsters", []):
            mid = m.get("id", "?")
            mtype = m.get("type")
            if mtype not in catalogs.monsters:
                errors.append(f"monster {mid} has unknown type '{mtype}'")
            pos = pos_of(m, f"monster {mid}")
            if pos is None:
                continue
            require_in_room(f"monster {mid}", pos, room_id)
            claim([pos], f"monster {mid}")

        for f in room.get("furniture", []):
            ftype = f.get("type")
            pos = pos_of(f, f"furniture '{ftype}'")
            if pos is None:
                continue
            label = f"furniture '{ftype}' at {fmt_pos(pos)}"
            if ftype not in catalogs.furniture:
                errors.append(f"{label} has unknown furniture type '{ftype}'")
                continue
            orientation = f.get("orientation", "N")
            if orientation not in ORIENTATIONS:
                errors.append(f"{label} has invalid orientation '{orientation}'")
                orientation = "N"
            cells = footprint_cells(pos, catalogs.furniture[ftype]["footprint"], orientation)
            for c in cells:
                if c not in board.room_squares[room_id]:
                    errors.append(
                        f"furniture '{ftype}' at {fmt_pos(pos)} doesn't fit inside "
                        f"{room_id} (footprint extends to {fmt_pos(c)})"
                    )
            claim(cells, label)

        for t in room.get("traps", []):
            pos = pos_of(t, f"trap({t.get('type')})")
            if pos is None:
                continue
            label = f"trap({t.get('type')}) at {fmt_pos(pos)}"
            require_in_room(label, pos, room_id)
            claim([pos], label)

    # -- corridor traps (top-level quest["corridorTraps"], parallel to
    # room traps; the design doc requires a corridor trap cap but
    # quest-schema.md only showed room-scoped traps, so this extends it) --
    for t in quest.get("corridorTraps", []):
        pos = pos_of(t, f"corridor trap({t.get('type')})")
        if pos is None:
            continue
        label = f"corridor trap({t.get('type')}) at {fmt_pos(pos)}"
        if pos not in board.corridor_squares:
            errors.append(f"{label} is not a corridor square")
        claim([pos], label)

    # -- doors: wall edge between two distinct, adjacent areas --
    for d in quest.get("doors", []):
        did = d.get("id", "?")
        squares = d.get("squares", [])
        if len(squares) != 2:
            errors.append(f"door {did} must declare exactly 2 squares, got {len(squares)}")
            continue
        a, b = (tuple(squares[0]), tuple(squares[1]))
        dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
        if dx + dy != 1:
            errors.append(
                f"door {did} squares {fmt_pos(a)}/{fmt_pos(b)} are not orthogonally adjacent"
            )
            continue
        area_a = board.area_of.get(a)
        area_b = board.area_of.get(b)
        if area_a is None or area_b is None:
            errors.append(f"door {did} touches a square outside the board ({fmt_pos(a)}/{fmt_pos(b)})")
            continue
        if area_a == area_b:
            errors.append(
                f"door {did} at {fmt_pos(a)}/{fmt_pos(b)} doesn't separate two areas "
                f"(both are {area_a}; corridor-to-corridor and same-room edges don't need doors)"
            )

    return errors
