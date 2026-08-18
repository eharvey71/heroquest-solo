"""Builds the initial game-state document for a fresh quest run.

Heroes start on the stairway's 2x2 footprint (one square each -- the
footprint is exactly 4 squares, which happens to match the max
heroCount of 4). Only the stairway room is revealed; monsters are
loaded into the roster at full body points immediately, but fog of war
governs what a caller actually shows -- see CLAUDE.md's "Room ids, not
coordinates, drive fog of war" note, and engine/zargon_turn.py's
existing "is this monster's location currently revealed" gate.
"""

from __future__ import annotations

from validator.catalogs import Catalogs

from .movement import Coord


class InvalidRosterError(ValueError):
    """The hero roster doesn't fit the quest (too many heroes, or none)."""


def _stairway_squares(quest: dict) -> list[Coord]:
    stairway = quest.get("stairway", {})
    pos = stairway.get("pos")
    if not pos:
        raise InvalidRosterError("quest has no stairway declared")
    x, y = pos
    return [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)]


def build_initial_game_state(*, quest: dict, catalogs: Catalogs, heroes: list[dict]) -> dict:
    """heroes: [{"id": "barbarian", "name": "Barbarian"}, ...], 1-4
    entries, order picks which stairway square each hero starts on.
    """
    if not 1 <= len(heroes) <= 4:
        raise InvalidRosterError(f"heroCount must be 1-4, got {len(heroes)}")

    stairway_room = quest.get("stairway", {}).get("room")
    if not stairway_room:
        raise InvalidRosterError("quest has no stairway room declared")
    squares = _stairway_squares(quest)

    hero_states = [
        {"id": h["id"], "name": h.get("name", h["id"]), "pos": list(squares[i]), "active": True}
        for i, h in enumerate(heroes)
    ]

    monsters: dict = {}
    for room in quest.get("rooms", {}).values():
        for m in room.get("monsters", []):
            catalog_entry = catalogs.monsters.get(m["type"], {})
            overrides = m.get("overrides", {})
            body = overrides.get("body", catalog_entry.get("body", 1))
            monsters[m["id"]] = {"pos": list(m["pos"]), "currentBody": body, "alive": True}

    return {
        "questId": None,  # filled in by the caller once the quest doc id is known
        "turn": 1,
        "phase": "hero",
        "heroes": hero_states,
        "monsters": monsters,
        "revealed": {"rooms": [stairway_room], "corridorSquares": []},
        "doors": {},
        "trapsTriggered": [],
        "searched": {},
        "log": [{"turn": 1, "text": "The party begins their quest."}],
    }
