"""Resolves the "search traps/secret doors" button (CLAUDE.md's
interface list) -- a separate action from "search treasure", per the
1989 rules a hero can search a room for hazards without drawing from
the treasure deck.

Unlike treasure (physical deck, app never learns the contents), traps
and secret doors are entirely quest-owned data the app already has --
so this search is fully digital: it reveals whatever's actually there.
Found traps go into the same trapsTriggered registry
engine/hero_movement.py uses, so stepping on a found trap later doesn't
re-log it as a fresh spring -- once known, it's known. Found secret
doors flip from "secret" to "closed": now a normal door, still
requiring the separate "open door" button per the interface list.

Scoped to the searching hero's room only: this room's floor traps
(quest.rooms[room_id].traps) and any secret door bordering it. Corridor
traps and furniture-contained traps (chest/tomb "contains.trap") are
out of scope for this button -- corridor traps are found by walking
into them (hero_movement.py), and furniture traps are a treasure-
search-time concern, not built yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from validator.catalogs import Board

from .hero_movement import _build_trap_lookup

Coord = tuple[int, int]


class RoomNotFoundError(ValueError):
    """room_id isn't a real room on the board."""


class InvalidTrapSearchError(ValueError):
    """The search can't happen right now: the hero isn't standing in
    the room, the room hasn't been revealed yet, or it's already been
    searched for traps/secret doors this quest.
    """


@dataclass
class FoundTrap:
    trap_id: str
    trap_type: str
    pos: Coord
    placement_instruction: str


@dataclass
class FoundSecretDoor:
    door_id: str
    squares: list[Coord]
    placement_instruction: str


@dataclass
class TrapSearchResult:
    room_id: str
    found_traps: list[FoundTrap] = field(default_factory=list)
    found_secret_doors: list[FoundSecretDoor] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


def resolve_trap_search(*, board: Board, quest: dict, game_state: dict, hero_id: str, room_id: str) -> TrapSearchResult:
    if room_id not in board.room_squares:
        raise RoomNotFoundError(f"room '{room_id}' not found on the board")

    heroes = game_state.get("heroes", [])
    hero = next((h for h in heroes if h["id"] == hero_id), None)
    if hero is None:
        raise InvalidTrapSearchError(f"hero '{hero_id}' not found in game state")
    hero_pos = tuple(hero["pos"])

    if board.area_of.get(hero_pos) != room_id:
        raise InvalidTrapSearchError(f"hero '{hero_id}' is not standing in room '{room_id}'")

    if room_id not in game_state.get("revealed", {}).get("rooms", []):
        raise InvalidTrapSearchError(f"room '{room_id}' has not been revealed yet")

    if game_state.get("searched", {}).get(room_id, {}).get("traps"):
        raise InvalidTrapSearchError(f"room '{room_id}' has already been searched for traps/secret doors")

    already_known = set(game_state.get("trapsTriggered", []))
    log = [f"{hero_id} searches {room_id} for traps and secret doors."]

    found_traps: list[FoundTrap] = []
    trap_lookup = _build_trap_lookup(quest)
    room_trap_prefix = f"{room_id}-T"
    for pos, (trap_id, trap_type) in trap_lookup.items():
        if not trap_id.startswith(room_trap_prefix) or trap_id in already_known:
            continue
        instruction = f"Place the {trap_type} trap tile at square [{pos[0]},{pos[1]}]."
        found_traps.append(FoundTrap(trap_id=trap_id, trap_type=trap_type, pos=pos, placement_instruction=instruction))
        log.append(f"{hero_id} finds a {trap_type} trap at [{pos[0]},{pos[1]}]! {instruction}")

    found_doors: list[FoundSecretDoor] = []
    door_states = game_state.get("doors", {})
    room_squares = board.room_squares[room_id]
    for d in quest.get("doors", []):
        squares = [tuple(s) for s in d["squares"]]
        state = door_states.get(d["id"], d.get("state"))
        if state != "secret" or not any(sq in room_squares for sq in squares):
            continue
        instruction = f"Place the closed door tile at squares {list(squares[0])}-{list(squares[1])}."
        found_doors.append(FoundSecretDoor(door_id=d["id"], squares=squares, placement_instruction=instruction))
        log.append(f"{hero_id} finds a secret door at {list(squares[0])}-{list(squares[1])}! {instruction}")

    if not found_traps and not found_doors:
        log.append("Nothing found.")

    return TrapSearchResult(room_id=room_id, found_traps=found_traps, found_secret_doors=found_doors, log=log)
