"""Resolves the "search for traps" and "search for secret doors"
buttons. The 1989 rulebook lists these as two DISTINCT hero actions
(Actions 4 and 5) alongside search-for-treasure, and a hero performs
only one action per turn -- doing both from a single button handed the
party a free action, so search_type selects one.

Unlike treasure (physical deck, app never learns the contents), traps
and secret doors are entirely quest-owned data the app already has --
so this search is fully digital: it reveals whatever's actually there.
Found traps go into game state's trapsFound registry -- deliberately
NOT trapsTriggered, which means SPRUNG. A found trap is still armed:
the rulebook springs it on a hero who walks in without jumping or
disarming, so knowing where it is buys the party a decision, not
immunity. Found secret
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
from .heroes import find_living_hero, living_heroes
from .line_of_sight import has_line_of_sight
from .movement import passable_door_edges

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


SEARCH_TYPES = ("traps", "secret_doors")


def resolve_trap_search(
    *, board: Board, quest: dict, game_state: dict, hero_id: str, room_id: str, search_type: str = "traps"
) -> TrapSearchResult:
    if search_type not in SEARCH_TYPES:
        raise InvalidTrapSearchError(f"search_type must be one of {SEARCH_TYPES}, got '{search_type}'")

    if room_id not in board.room_squares:
        raise RoomNotFoundError(f"room '{room_id}' not found on the board")

    heroes = living_heroes(game_state)
    hero = find_living_hero(game_state, hero_id)
    if hero is None:
        raise InvalidTrapSearchError(f"hero '{hero_id}' is not in this game, or has fallen")
    hero_pos = tuple(hero["pos"])

    if board.area_of.get(hero_pos) != room_id:
        raise InvalidTrapSearchError(f"hero '{hero_id}' is not standing in room '{room_id}'")

    if room_id not in game_state.get("revealed", {}).get("rooms", []):
        raise InvalidTrapSearchError(f"room '{room_id}' has not been revealed yet")

    searched_flag = "traps" if search_type == "traps" else "secretDoors"
    if game_state.get("searched", {}).get(room_id, {}).get(searched_flag):
        raise InvalidTrapSearchError(f"room '{room_id}' has already been searched for {search_type.replace('_', ' ')}")

    already_known = set(game_state.get("trapsFound", [])) | set(game_state.get("trapsTriggered", []))
    log = [f"{hero_id} searches {room_id} for {search_type.replace('_', ' ')}."]

    # "You can only search for traps [or secret doors] if there are no
    # monsters visible to you" (1989 rulebook, Actions 4 and 5) -- now
    # the rulebook's actual sightline (page 15's "SEE"), not the older
    # "same room" approximation. Figures block sight here: this is
    # targeting, not terrain reveal.
    open_edges = passable_door_edges(quest.get("doors", []), game_state.get("doors", {}))
    walls = frozenset(
        {tuple(sq) for sq in quest.get("blockedSquares", [])}
        | {tuple(sq) for sq in game_state.get("collapsedSquares", [])}
    )
    live_monsters = [tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")]
    figures = frozenset(live_monsters) | {tuple(h["pos"]) for h in heroes}
    if any(
        has_line_of_sight(board, hero_pos, mpos, open_door_edges=open_edges, walls=walls, figures=figures)
        for mpos in live_monsters
    ):
        raise InvalidTrapSearchError(f"'{hero_id}' can see a monster -- a hero can't search while one watches")

    found_traps: list[FoundTrap] = []
    trap_lookup = _build_trap_lookup(quest) if search_type == "traps" else {}
    room_trap_prefix = f"{room_id}-T"
    for pos, (trap_id, trap_type) in trap_lookup.items():
        if not trap_id.startswith(room_trap_prefix) or trap_id in already_known:
            continue
        # No tile goes down here. "Zargon will NOT put any trap tiles out
        # on the board. At this time, they are still concealed and
        # unsprung" (1989 rulebook, How A Hero Searches For Traps) -- the
        # tile is placed only when the trap is actually sprung, which
        # hero_movement handles.
        instruction = f"Zargon points out the {trap_type} trap at square [{pos[0]},{pos[1]}] -- no tile yet, it is still unsprung."
        found_traps.append(FoundTrap(trap_id=trap_id, trap_type=trap_type, pos=pos, placement_instruction=instruction))
        log.append(f"{hero_id} finds a {trap_type} trap at [{pos[0]},{pos[1]}]. {instruction}")

    found_doors: list[FoundSecretDoor] = []
    door_states = game_state.get("doors", {})
    room_squares = board.room_squares[room_id]
    for d in quest.get("doors", []) if search_type == "secret_doors" else []:
        squares = [tuple(s) for s in d["squares"]]
        state = door_states.get(d["id"], d.get("state"))
        if state != "secret" or not any(sq in room_squares for sq in squares):
            continue
        instruction = f"Place the secret door tile at squares {list(squares[0])}-{list(squares[1])}."
        found_doors.append(FoundSecretDoor(door_id=d["id"], squares=squares, placement_instruction=instruction))
        log.append(f"{hero_id} finds a secret door at {list(squares[0])}-{list(squares[1])}! {instruction}")

    if not found_traps and not found_doors:
        log.append("Nothing found.")

    return TrapSearchResult(room_id=room_id, found_traps=found_traps, found_secret_doors=found_doors, log=log)
