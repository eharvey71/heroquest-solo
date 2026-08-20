"""Resolves the "open door" button (CLAUDE.md's interface list: a hard
stop during movement, opened as its own separate action).

Physically this REPLACES the piece: every door is placed closed, and
Zargon swaps the closed piece for an open one when a hero opens it
(the box holds 16 open and 5 closed pieces -- an inventory of pieces,
not a limit on how many doors a quest may have).

Opening a closed door reveals the far room immediately, matching how a
human Zargon populates a room as soon as the door swings open -- the
hero doesn't need to step inside first. This is the same sightline this
app already relies on for guard-objective engagement (CLAUDE.md: "OR
standing at an open doorway into it"). Corridor squares on the far side
are NOT flood-revealed here -- a corridor stretches out past what a
doorway alone lets you see, and reveals progressively as walked
(engine/hero_movement.py), same as if the door had already been open.

Only closed -> open is handled. Secret doors need a search
resolution and secret doors need to be found via a search first --
neither is this button's job.
"""

from __future__ import annotations

from dataclasses import dataclass

from validator.catalogs import CORRIDOR, Board

Coord = tuple[int, int]


class DoorNotFoundError(ValueError):
    """No door with this id exists in the quest."""


class InvalidDoorOpenError(ValueError):
    """The door can't be opened right now: the hero isn't standing at
    it, it's already open, or it is still secret and requires a
    different resolution than this button.
    """


def effective_door_state(door: dict, door_states: dict) -> str:
    """A door's state right now, treating a quest-declared "open" as
    closed.

    Quest generation marks most doors "open" to mean "no lock, no
    secret" -- it is not a claim that the door stands open on turn one.
    Game state seeds every passable door closed
    (engine/create_game.py), but games created before that carry no
    door entry at all, so the fallback has to re-assert the rule rather
    than trust the quest's word: nothing is walkable until a hero stops
    at it and Zargon opens it.
    """
    state = door_states.get(door.get("id"))
    if state is not None:
        return state
    quest_state = door.get("state")
    # Anything that isn't a secret door starts closed. That includes the
    # retired "locked" state, so pre-existing quests stay playable.
    return quest_state if quest_state == "secret" else "closed"


@dataclass
class OpenDoorResult:
    door_id: str
    new_state: str
    revealed_room: str | None
    placement_instruction: str
    log: list[str]


def resolve_open_door(*, board: Board, quest: dict, game_state: dict, hero_id: str, door_id: str) -> OpenDoorResult:
    door = next((d for d in quest.get("doors", []) if d["id"] == door_id), None)
    if door is None:
        raise DoorNotFoundError(f"door '{door_id}' not found in quest")

    squares = [tuple(s) for s in door["squares"]]
    if len(squares) != 2:
        raise DoorNotFoundError(f"door '{door_id}' has a malformed squares list")

    heroes = game_state.get("heroes", [])
    hero = next((h for h in heroes if h["id"] == hero_id), None)
    if hero is None:
        raise InvalidDoorOpenError(f"hero '{hero_id}' not found in game state")
    hero_pos = tuple(hero["pos"])

    if hero_pos not in squares:
        raise InvalidDoorOpenError(f"hero '{hero_id}' is not standing at door '{door_id}'")

    state = effective_door_state(door, game_state.get("doors", {}))

    if state == "open":
        raise InvalidDoorOpenError(f"door '{door_id}' is already open")
    if state == "secret":
        raise InvalidDoorOpenError(f"door '{door_id}' is secret -- must be found via search first")
    if state != "closed":
        raise InvalidDoorOpenError(f"door '{door_id}' has an unrecognized state '{state}'")

    far_square = squares[1] if hero_pos == squares[0] else squares[0]
    far_area = board.area_of.get(far_square)

    placement_instruction = (
        f"Replace the closed door piece at squares {list(squares[0])}-{list(squares[1])} "
        f"with an open door piece."
    )

    revealed_room = None
    # The tile instruction goes IN the log line, as every other engine
    # does, so the client never has to echo it as a second stream (which
    # landed the instructions out of order at the bottom of the log).
    log = [f"{hero_id} opens the door at {list(squares[0])}-{list(squares[1])}. {placement_instruction}"]
    if far_area is not None and far_area != CORRIDOR:
        revealed_room = far_area
        log.append(f"{far_area} revealed.")

    return OpenDoorResult(
        door_id=door_id,
        new_state="open",
        revealed_room=revealed_room,
        placement_instruction=placement_instruction,
        log=log,
    )
