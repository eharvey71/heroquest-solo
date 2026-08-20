"""Resolves a hero's traced movement path (CLAUDE.md: "hero movement
entered as a path drag/click-trace ... required so traps trigger
mid-move and Zargon knows positions").

Door-opening is explicitly its own button in CLAUDE.md's interface
list, separate from movement -- so a closed door is a hard stop here,
not something movement auto-opens. The hero reaches the threshold,
gets told which door is in the way, and traces a new path after
clicking "open door" as a separate action. This is a direct reading of
settled design, not a guess.

Springing a trap ENDS the hero's movement (1989 rulebook, verified
against the owner's photos: every trap description finishes "This ends
your turn"). The two trap types the generator emits end it differently:
a pit swallows the hero, who ends ON the trap square with the tile
placed under the figure; a falling block brings the ceiling down, so
the hero never takes the square -- it becomes a PERMANENT block for
heroes and monsters alike, and the hero stays where they were. The
rulebook lets that hero step forward or back; the app can't prompt
mid-move, so it picks "back", the choice that can't strand them.

Monsters,
furniture, and blocked squares DO halt movement, same as a closed door
-- partial credit for however far the hero got, not a rejected request.

Heroes may pass through fellow HEROES but nothing else (CLAUDE.md's
rules-edition note). Furniture is solid: a table or tomb is a physical
obstruction on the real board, so a traced path can't cross it.

KNOWN traps are distinct from SPRUNG ones. A trap the party found by
searching is still armed -- the rulebook springs it on anyone who
walks in without jumping or disarming -- so movement STOPS in front of
it ("known_trap") and the hero chooses: jump it, disarm it, or step on
it deliberately. Conflating the two registries made searching a room
disarm every trap in it for free.

Sharing a square is normally illegal, with the rulebook's two stated
exceptions: "When on the stairs or in pit traps, sharing a square is
permitted." Both are computable from quest data plus which pits have
sprung, so the app enforces the rule and its exceptions rather than
approximating either.

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
    stopped_at_trap_id: str | None = None
    log: list[str] = field(default_factory=list)

    # Everything a caller needs to merge back into game state -- the
    # union of what was already revealed plus what this move added.
    revealed_rooms: set[str] = field(default_factory=set)
    revealed_corridor_squares: set[Coord] = field(default_factory=set)
    traps_triggered: set[str] = field(default_factory=set)  # sprung
    traps_found: set[str] = field(default_factory=set)  # known, still armed
    collapsed_squares: set[Coord] = field(default_factory=set)


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


def shareable_squares(quest: dict, game_state: dict) -> set:
    """Squares where figures may stack: the stairway's 2x2 footprint and
    any SPRUNG pit (1989 rulebook -- an unsprung pit is still a covered
    floor, so it shares nothing).
    """
    squares = set()
    stairway = quest.get("stairway", {})
    pos = stairway.get("pos")
    if pos:
        x, y = pos
        squares.update({(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)})

    sprung = set(game_state.get("trapsTriggered", []))
    for trap_pos, (trap_id, trap_type) in _build_trap_lookup(quest).items():
        if trap_type == "pit" and trap_id in sprung:
            squares.add(trap_pos)
    return squares


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
    # trapsTriggered keeps its original meaning: traps already SPRUNG.
    # trapsFound is the newer, separate registry of traps the party knows
    # about but which are still armed. A legacy doc with search results
    # folded into trapsTriggered just leaves those few traps harmless in
    # that one game -- no migration needed.
    traps_sprung = set(game_state.get("trapsTriggered", []))
    traps_found = set(game_state.get("trapsFound", []))
    blocked_squares = {tuple(s) for s in quest.get("blockedSquares", [])}
    # Squares where a falling block has already come down this game --
    # quest data can't know these; they accumulate at runtime.
    collapsed = {tuple(s) for s in game_state.get("collapsedSquares", [])}
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
    stopped_trap_id: str | None = None

    for prev, cur in zip(path, path[1:]):
        if board.area_of.get(cur) is None:
            stopped_reason = "off_board"
            break
        if cur in blocked_squares or cur in collapsed:
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

        trap = trap_lookup.get(cur)
        if trap is not None and trap[0] not in traps_sprung and trap[0] in traps_found:
            # The party already knows this one is here. Walking on would
            # spring it, so stop and let the hero decide.
            stopped_reason = "known_trap"
            stopped_trap_id = trap[0]
            log.append(f"{hero_id} stops in front of the known {trap[1]} trap at [{cur[0]},{cur[1]}].")
            break

        springing = trap is not None and trap[0] not in traps_sprung

        if springing and trap[1] == "falling_block":
            # The ceiling comes down before the hero is through: they do
            # not take the square, and it is sealed for good.
            trap_id, trap_type = trap
            traps_sprung.add(trap_id)
            collapsed.add(cur)
            instruction = (
                f"Place the falling block trap tile at square [{cur[0]},{cur[1]}] -- "
                f"that square is blocked for the rest of the quest."
            )
            triggered.append(TriggeredTrap(trap_id=trap_id, trap_type=trap_type, pos=cur, placement_instruction=instruction))
            log.append(
                f"{hero_id} springs a falling block trap at [{cur[0]},{cur[1]}]! The ceiling caves in. "
                f"Roll 3 combat dice -- 1 Body Point per skull, no defend dice. {instruction}"
            )
            stopped_reason = "trap_sprung"
            break

        applied_path.append(cur)

        if springing:
            trap_id, trap_type = trap
            traps_sprung.add(trap_id)
            instruction = f"Place the pit trap tile at square [{cur[0]},{cur[1]}], under the hero's figure."
            triggered.append(TriggeredTrap(trap_id=trap_id, trap_type=trap_type, pos=cur, placement_instruction=instruction))
            log.append(
                f"{hero_id} stumbles into a pit at [{cur[0]},{cur[1]}]! 1 Body Point of damage, and the move ends here. "
                f"{instruction}"
            )
            stopped_reason = "trap_sprung"
            break

    final_pos = applied_path[-1]
    if final_pos in other_hero_squares and final_pos not in shareable_squares(quest, game_state):
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
        stopped_at_trap_id=stopped_trap_id,
        log=log,
        revealed_rooms=revealed_rooms,
        revealed_corridor_squares=revealed_corridor,
        traps_triggered=traps_sprung,
        traps_found=traps_found,
        collapsed_squares=collapsed,
    )
