"""What a Chaos spell does to a hero's turn."""

import pytest

from engine.doors import InvalidDoorOpenError, resolve_open_door
from engine.hero_movement import IllegalMovementError, resolve_hero_movement
from engine.hero_status import (
    SpellNotOnHeroError,
    add_status,
    attempt_break,
    blocking_status,
    expire_turn_statuses,
    is_afraid,
    statuses_for,
)

D1 = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "closed"}


def _state():
    return {
        "heroes": [{"id": "barbarian", "name": "Barbarian", "pos": [4, 1], "alive": True}],
        "monsters": {},
        "revealed": {"rooms": ["R1"], "corridorSquares": []},
        "doors": {"D1": "closed"},
        "trapsTriggered": [],
        "heroStatus": {},
    }


def _quest():
    return {"doors": [D1], "blockedSquares": [], "rooms": {}, "corridorTraps": []}


def test_fear_does_not_stop_a_hero_acting():
    state = _state()
    add_status(state, "barbarian", status="afraid", spell="fear", turn=3)
    assert blocking_status(state, "barbarian") is None
    assert is_afraid(state, "barbarian") is True


@pytest.mark.parametrize("status", ["asleep", "paralyzed", "commanded", "becalmed"])
def test_a_held_hero_cannot_move(status, catalogs):
    state = _state()
    add_status(state, "barbarian", status=status, spell="sleep", turn=1)
    with pytest.raises(IllegalMovementError):
        resolve_hero_movement(
            board=catalogs.board, catalogs=catalogs, quest=_quest(), game_state=state,
            hero_id="barbarian", path=[[4, 1], [3, 1]],
        )


def test_a_held_hero_cannot_open_a_door(catalogs):
    state = _state()
    add_status(state, "barbarian", status="asleep", spell="sleep", turn=1)
    with pytest.raises(InvalidDoorOpenError) as excinfo:
        resolve_open_door(
            board=catalogs.board, quest=_quest(), game_state=state, hero_id="barbarian", door_id="D1"
        )
    assert "asleep" in str(excinfo.value)


def test_the_same_spell_twice_does_not_stack():
    state = _state()
    add_status(state, "barbarian", status="asleep", spell="sleep", turn=1)
    add_status(state, "barbarian", status="asleep", spell="sleep", turn=4)
    assert len(statuses_for(state, "barbarian")) == 1
    assert statuses_for(state, "barbarian")[0]["since"] == 4


def test_a_six_breaks_the_spell():
    state = _state()
    add_status(state, "barbarian", status="asleep", spell="sleep", turn=1)
    broke, log = attempt_break(state, "barbarian", "Barbarian", rolled_six=True)
    assert broke is True
    assert blocking_status(state, "barbarian") is None
    assert any("breaks free" in line for line in log)


def test_no_six_leaves_the_hero_held():
    state = _state()
    add_status(state, "barbarian", status="asleep", spell="sleep", turn=1)
    broke, log = attempt_break(state, "barbarian", "Barbarian", rolled_six=False)
    assert broke is False
    assert blocking_status(state, "barbarian") is not None


def test_breaking_nothing_is_an_error():
    with pytest.raises(SpellNotOnHeroError):
        attempt_break(_state(), "barbarian", "Barbarian", rolled_six=True)


def test_a_tempest_expires_after_the_turn_it_costs():
    state = _state()
    add_status(state, "barbarian", status="becalmed", spell="tempest", turn=5, misses_turns=1)

    # End of the turn it landed on: the hero has not yet missed a turn.
    expire_turn_statuses(state, 5)
    assert blocking_status(state, "barbarian") is not None

    # End of the turn they missed: gone.
    expire_turn_statuses(state, 6)
    assert blocking_status(state, "barbarian") is None
