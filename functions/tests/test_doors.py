import pytest

from engine.doors import DoorNotFoundError, InvalidDoorOpenError, resolve_open_door


def _hero_at(pos):
    return [{"id": "barbarian", "name": "Barbarian", "pos": list(pos), "active": True}]


def test_opens_closed_door_and_reveals_far_room(good_quest_4h, catalogs):
    # D3: [[8,4],[9,4]] closed, R5<->R3 (real board.json coordinates).
    game_state = {"heroes": _hero_at((8, 4)), "doors": {}, "revealed": {"rooms": [], "corridorSquares": []}}
    result = resolve_open_door(
        board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", door_id="D3"
    )
    assert result.new_state == "open"
    assert result.revealed_room == "R3"
    assert result.log


def test_hero_can_open_from_either_side(good_quest_4h, catalogs):
    game_state = {"heroes": _hero_at((9, 4)), "doors": {}, "revealed": {"rooms": [], "corridorSquares": []}}
    result = resolve_open_door(
        board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", door_id="D3"
    )
    assert result.revealed_room == "R5"


def test_rejects_unknown_door(good_quest_4h, catalogs):
    game_state = {"heroes": _hero_at((8, 4)), "doors": {}, "revealed": {"rooms": [], "corridorSquares": []}}
    with pytest.raises(DoorNotFoundError):
        resolve_open_door(
            board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", door_id="D99"
        )


def test_rejects_hero_not_at_door(good_quest_4h, catalogs):
    game_state = {"heroes": _hero_at((1, 1)), "doors": {}, "revealed": {"rooms": [], "corridorSquares": []}}
    with pytest.raises(InvalidDoorOpenError):
        resolve_open_door(
            board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", door_id="D3"
        )


def test_rejects_already_open_door(good_quest_4h, catalogs):
    # "Already open" is a GAME-state fact -- a hero opened it earlier
    # this quest. Quest data calling a door "open" does not mean it
    # stands open (see engine/create_game.py._initial_door_states).
    game_state = {
        "heroes": _hero_at((4, 1)),
        "doors": {"D1": "open"},
        "revealed": {"rooms": [], "corridorSquares": []},
    }
    with pytest.raises(InvalidDoorOpenError):
        resolve_open_door(
            board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", door_id="D1"
        )


def test_quest_open_door_still_needs_opening(good_quest_4h, catalogs):
    # D1 is "open" in the quest fixture and the game doc records no
    # state for it (a game created before doors were seeded closed).
    # It must still be openable -- i.e. it is NOT standing open.
    game_state = {"heroes": _hero_at((4, 1)), "doors": {}, "revealed": {"rooms": [], "corridorSquares": []}}
    result = resolve_open_door(
        board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", door_id="D1"
    )
    assert result.new_state == "open"


def test_rejects_secret_door(good_quest_4h, catalogs):
    game_state = {
        "heroes": _hero_at((8, 4)),
        "doors": {"D3": "secret"},
        "revealed": {"rooms": [], "corridorSquares": []},
    }
    with pytest.raises(InvalidDoorOpenError):
        resolve_open_door(
            board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", door_id="D3"
        )


def test_game_state_door_override_takes_precedence_over_quest_default(good_quest_4h, catalogs):
    # D1 defaults to "open" in the quest, but game state can override it
    # back to "closed" (shouldn't normally happen, but the engine must
    # trust live state over the quest's initial declaration).
    game_state = {
        "heroes": _hero_at((4, 1)),
        "doors": {"D1": "closed"},
        "revealed": {"rooms": [], "corridorSquares": []},
    }
    result = resolve_open_door(
        board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", door_id="D1"
    )
    assert result.new_state == "open"
