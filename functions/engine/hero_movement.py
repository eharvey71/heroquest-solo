"""Resolves a hero's traced movement path (CLAUDE.md: "hero movement
entered as a path drag/click-trace ... required so traps trigger
mid-move and Zargon knows positions").

Door-opening is explicitly its own button in CLAUDE.md's interface
list, separate from movement -- so a closed door is a hard stop here,
not something movement auto-opens. The hero reaches the threshold,
gets told which door is in the way, and traces a new path after
clicking "open door" as a separate action. This is a direct reading of
settled design, not a guess.

Traps do NOT halt movement (documented assumption -- the 1989 rules
don't stop a hero's move on a sprung pit/falling-block trap, just deal
damage); the path keeps processing past a trap trigger. Monsters,
furniture, and blocked squares DO halt movement, same as a closed door
-- partial credit for however far the hero got, not a rejected request.

Heroes may pass through fellow HEROES but nothing else (CLAUDE.md's
rules-edition note). Furniture is solid: a table or tomb is a physical
obstruction on the real board, so a traced path can't cross it.

This module never touches hero body points -- physical-only, same
boundary as everywhere else in this app.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from validator.catalogs import CORRIDOR, Board, Catalogs
from validator.geometry import furniture_squares

from .doors import effective_door_state

Coord = tuple[int, int]


class IllegalMovementError(ValueError):
    """The request itself is malformed or violates a hard rule (not a
    natural in-game obstacle) -- start position mismatch, non-adjacent
    steps, or an illegal final resting square. A well-behaved client
    shouldn't produce these; they're a defensive backstop.
    """


@dataclass
class TriggeredTrap:
    trap_id: str
    trap_type: str
    pos: Coord
    placement_instruction: str


@dataclass
class HeroMovementResult:
    hero_id: str
    final_pos: Coord
    path_taken: list[Coord]
    newly_revealed_rooms: list[str] = field(default_factory=list)
    newly_revealed_corridor_squares: list[Coord] = field(default_factory=list)
    triggered_traps: list[TriggeredTrap] = field(default_factory=list)
    # None means the full requested path was walked without interruption.
    # "closed_door" | "locked_door" | "monster_blocked" | "blocked_square"
    # | "furniture_blocked" | "no_door" | "off_board"
    stopped_reason: str | None = None
    stopped_at_door_id: str | None = None
    log: list[str] = field(default_factory=list)

    # Everything a caller needs to merge back into game state -- the
    # union of what was already revealed plus what this move added.
    revealed_rooms: set[str] = field(default_factory=set)
    revealed_corridor_squares: set[Coord] = field(default_factory=set)
    traps_triggered: set[str] = field(default_factory=set)


def _build_trap_lookup(quest: dict) -> dict[Coord, tuple[str, str]]:
    """pos -> (trap_id, trap_type). Trap ids aren't part of the quest
    schema (design/quest-schema.md's traps are anonymous), so they're
    synthesized deterministically here: "<room>-T<n>" / "CORRIDOR-T<n>",
    matching the game-state example in quest-schema.md ("R3-T1").
    """
    lookup: dict[Coord, tuple[str, str]] = {}
    for room_id, room in quest.get("rooms", {}).items():
        for i, trap in enumerate(room.get("traps", []), start=1):
            lookup[tuple(trap["pos"])] = (f"{room_id}-T{i}", trap["type"])
    for i, trap in enumerate(quest.get("corridorTraps", []), start=1):
        lookup[tuple(trap["pos"])] = (f"CORRIDOR-T{i}", trap["type"])
    return lookup


def _door_by_edge(quest_doors: list[dict]) -> dict[frozenset, dict]:
    result = {}
    for d in quest_doors:
        squares = d.get("squares", [])
        if len(squares) == 2:
            result[frozenset((tuple(squares[0]), tuple(squares[1])))] = d
    return result


def resolve_hero_movement(
    *,
    board: Board,
    catalogs: Catalogs,
    quest: dict,
    game_state: dict,
    hero_id: str,
    path: list,
) -> HeroMovementResult:
    path = [tuple(p) for p in path]
    if len(path) < 1:
        raise IllegalMovementError("path must contain at least the hero's current position")

    heroes = game_state.get("heroes", [])
    hero = next((h for h in heroes if h["id"] == hero_id), None)
    if hero is None:
        raise IllegalMovementError(f"hero '{hero_id}' not found in game state")
    if path[0] != tuple(hero["pos"]):
        raise IllegalMovementError("path must start at the hero's current position")

    for prev, cur in zip(path, path[1:]):
        if abs(prev[0] - cur[0]) + abs(prev[1] - cur[1]) != 1:
            raise IllegalMovementError(f"path step {prev} -> {cur} is not orthogonally adjacent")

    revealed_rooms = set(game_state.get("revealed", {}).get("rooms", []))
    revealed_corridor = {tuple(s) for s in game_state.get("revealed", {}).get("corridorSquares", [])}
    door_states = game_state.get("doors", {})
    traps_triggered = set(game_state.get("trapsTriggered", []))
    blocked_squares = {tuple(s) for s in quest.get("blockedSquares", [])}
    furniture = furniture_squares(quest, catalogs)
    other_hero_squares = {tuple(h["pos"]) for h in heroes if h["id"] != hero_id}
    monster_squares = {tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")}

    trap_lookup = _build_trap_lookup(quest)
    door_by_edge = _door_by_edge(quest.get("doors", []))

    newly_revealed_rooms: list[str] = []
    newly_revealed_corridor: list[Coord] = []
    triggered: list[TriggeredTrap] = []
    log: list[str] = []

    applied_path = [path[0]]
    stopped_reason: str | None = None
    stopped_door_id: str | None = None

    for prev, cur in zip(path, path[1:]):
        if board.area_of.get(cur) is None:
            stopped_reason = "off_board"
            break
        if cur in blocked_squares:
            stopped_reason = "blocked_square"
            break
        if cur in furniture:
            stopped_reason = "furniture_blocked"
            break
        if cur in monster_squares:
            stopped_reason = "monster_blocked"
            break

        prev_area = board.area_of.get(prev)
        cur_area = board.area_of.get(cur)

        if cur_area != prev_area:
            door = door_by_edge.get(frozenset((prev, cur)))
            if door is None:
                stopped_reason = "no_door"
                break
            door_id = door["id"]
            state = effective_door_state(door, door_states)
            if state in ("locked", "secret"):
                stopped_reason = "locked_door"
                stopped_door_id = door_id
                break
            if state == "closed":
                stopped_reason = "closed_door"
                stopped_door_id = door_id
                break
            if cur_area != CORRIDOR and cur_area not in revealed_rooms:
                revealed_rooms.add(cur_area)
                newly_revealed_rooms.append(cur_area)
                log.append(f"{cur_area} revealed.")

        if cur_area == CORRIDOR and cur not in revealed_corridor:
            revealed_corridor.add(cur)
            newly_revealed_corridor.append(cur)

        applied_path.append(cur)

        if cur in trap_lookup:
            trap_id, trap_type = trap_lookup[cur]
            if trap_id not in traps_triggered:
                traps_triggered.add(trap_id)
                instruction = f"Place the {trap_type} trap tile at square [{cur[0]},{cur[1]}]."
                triggered.append(TriggeredTrap(trap_id=trap_id, trap_type=trap_type, pos=cur, placement_instruction=instruction))
                log.append(f"{hero_id} triggers a {trap_type} trap at [{cur[0]},{cur[1]}]! {instruction}")

    final_pos = applied_path[-1]
    if final_pos in other_hero_squares:
        raise IllegalMovementError(f"path cannot end on a square occupied by another hero ({final_pos})")

    return HeroMovementResult(
        hero_id=hero_id,
        final_pos=final_pos,
        path_taken=applied_path,
        newly_revealed_rooms=newly_revealed_rooms,
        newly_revealed_corridor_squares=newly_revealed_corridor,
        triggered_traps=triggered,
        stopped_reason=stopped_reason,
        stopped_at_door_id=stopped_door_id,
        log=log,
        revealed_rooms=revealed_rooms,
        revealed_corridor_squares=revealed_corridor,
        traps_triggered=traps_triggered,
    )
