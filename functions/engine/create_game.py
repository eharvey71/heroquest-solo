"""Builds the initial game-state document for a fresh quest run.

Heroes start on the stairway's 2x2 footprint (one square each -- the
footprint is exactly 4 squares, which happens to match the max
heroCount of 4). Only the stairway room is revealed; monsters are
loaded into the roster at full body points immediately, but fog of war
governs what a caller actually shows -- see CLAUDE.md's "Room ids, not
coordinates, drive fog of war" note, and engine/zargon_turn.py's
existing "is this monster's location currently revealed" gate.

Every door starts CLOSED (see _initial_door_states): no hero passes a
door until they stop at it and tell Zargon to open it.
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


def _initial_door_states(quest: dict) -> dict:
    """door_id -> starting state, with every passable door CLOSED.

    The 1989 rules give the hero no way through a door except stopping
    at it and telling Zargon to open it -- so a door may never start in
    a state movement can walk straight through. Quest generation marks
    most doors "open", meaning only "no lock, no secret"; that is a
    statement about the door's KIND, not about it standing open on turn
    one, and taking it literally let heroes stroll into unrevealed rooms
    (and onto whatever waited behind the door).

    Secret doors keep their state: they must be found by searching
    before the open-door button applies (engine/doors.py).
    """
    states = {}
    for d in quest.get("doors", []):
        door_id = d.get("id")
        if not door_id:
            continue
        state = d.get("state")
        states[door_id] = state if state == "secret" else "closed"
    return states


def build_initial_game_state(
    *,
    quest: dict,
    catalogs: Catalogs,
    heroes: list[dict],
    spellbooks: dict | None = None,
    mode: str = "traditional",
) -> dict:
    """heroes: [{"id": "barbarian", "name": "Barbarian"}, ...], 1-4
    entries, order picks which stairway square each hero starts on.

    spellbooks: {"wizard": ["Fire","Air","Earth"], "elf": ["Water"]} --
    which elements each caster took at the table. The Wizard picks
    three, the Elf one of what's left (engine/hero_spells.py), and a
    hero can only cast from their own elements.

    mode: "traditional" (exactly the game as it always was) or
    "expanded" (the quest's side quests are in play and its required
    gate, if any, starts closed) -- design/side-quests-design.md
    section 0. An expanded game on a quest with no side quests is just
    a traditional one.
    """
    if not 1 <= len(heroes) <= 4:
        raise InvalidRosterError(f"heroCount must be 1-4, got {len(heroes)}")

    stairway_room = quest.get("stairway", {}).get("room")
    if not stairway_room:
        raise InvalidRosterError("quest has no stairway room declared")
    squares = _stairway_squares(quest)

    hero_states = [
        {"id": h["id"], "name": h.get("name", h["id"]), "pos": list(squares[i]), "alive": True}
        for i, h in enumerate(heroes)
    ]

    monsters: dict = {}
    for room in quest.get("rooms", {}).values():
        for m in room.get("monsters", []):
            catalog_entry = catalogs.monsters.get(m["type"], {})
            overrides = m.get("overrides", {})
            body = overrides.get("body", catalog_entry.get("body", 1))
            monsters[m["id"]] = {"type": m["type"], "pos": list(m["pos"]), "currentBody": body, "alive": True}

    expanded = mode == "expanded" and bool(quest.get("sideQuests"))
    gate = None
    if expanded and quest.get("gate"):
        gate = {**quest["gate"], "state": "closed"}

    return {
        "questId": None,  # filled in by the caller once the quest doc id is known
        "mode": "expanded" if expanded else "traditional",
        "sideQuests": {},  # id -> progress, absent until a scene is begun (engine/side_quests.py)
        "pendingSideQuest": None,  # the scene in progress, locking the main game
        "gate": gate,  # the required scene's hold on the objective; None when traditional
        "artifactsHeld": {},  # artifactId -> heroId, from side-quest rewards (placement-only)
        "turn": 1,
        "phase": "hero",
        "heroPhaseSegment": 1,  # lone-hero parties get 2 hero phases per turn; see engine/end_turn.py
        "status": "in_progress",  # -> "complete" only once a hero is back at the stairway
        "objectiveComplete": False,  # stage 1 of 2; see main._mark_objective_if_complete
        "heroes": hero_states,
        "monsters": monsters,
        "revealed": {"rooms": [stairway_room], "corridorSquares": []},
        "doors": _initial_door_states(quest),
        "trapsTriggered": [],  # traps already SPRUNG
        "trapsFound": [],  # traps the party knows about but are still armed
        "collapsedSquares": [],  # squares sealed by a sprung falling block
        "searched": {},
        "spellbooks": spellbooks or {},  # caster -> elements taken at setup
        "spellsCast": [],  # each hero spell card is spent once per quest
        "chaosSpellsCast": [],  # ...and so is each of Zargon's twelve
        "heroStatus": {},  # asleep / paralyzed / commanded / becalmed / afraid
        "monsterStatus": {},  # asleep (Sleep) / becalmed (Tempest)
        "log": [{"turn": 1, "text": "The party begins their quest."}],
    }
