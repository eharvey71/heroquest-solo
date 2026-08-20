import pytest

from engine.trap_search import InvalidTrapSearchError, RoomNotFoundError, resolve_trap_search


def _hero_at(pos):
    return [{"id": "barbarian", "name": "Barbarian", "pos": list(pos), "active": True}]


def _game_state(pos, revealed_rooms, searched=None, doors=None, traps_triggered=None):
    return {
        "heroes": _hero_at(pos),
        "revealed": {"rooms": revealed_rooms, "corridorSquares": []},
        "searched": searched or {},
        "doors": doors or {},
        "trapsTriggered": traps_triggered or [],
    }


def test_finds_room_trap(good_quest_4h, catalogs):
    # R3 has a pit trap at [9,5] (real fixture data) -- synthesized id "R3-T1".
    game_state = _game_state((9, 5), ["R3"])
    result = resolve_trap_search(board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", room_id="R3")
    assert len(result.found_traps) == 1
    trap = result.found_traps[0]
    assert trap.trap_id == "R3-T1"
    assert trap.trap_type == "pit"
    assert trap.pos == (9, 5)


def test_finds_secret_door_bordering_room(good_quest_4h, catalogs):
    # D3 [[8,4],[9,4]] borders R3 at (9,4); overridden to secret for this test.
    game_state = _game_state((9, 5), ["R3"], doors={"D3": "secret"})
    result = resolve_trap_search(
        board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian",
        room_id="R3", search_type="secret_doors",
    )
    assert len(result.found_secret_doors) == 1
    assert result.found_secret_doors[0].door_id == "D3"


def test_already_known_trap_not_reported_again(good_quest_4h, catalogs):
    game_state = _game_state((9, 5), ["R3"], traps_triggered=["R3-T1"])
    result = resolve_trap_search(board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", room_id="R3")
    assert result.found_traps == []
    assert "Nothing found." in result.log


def test_no_traps_or_doors_logs_nothing_found(good_quest_4h, catalogs):
    # R1 (stairway room) has no traps or secret doors in the fixture.
    game_state = _game_state((1, 1), ["R1"])
    result = resolve_trap_search(board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", room_id="R1")
    assert result.found_traps == []
    assert result.found_secret_doors == []
    assert "Nothing found." in result.log


def test_rejects_unknown_room(good_quest_4h, catalogs):
    game_state = _game_state((9, 5), ["R3"])
    with pytest.raises(RoomNotFoundError):
        resolve_trap_search(board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", room_id="R99")


def test_rejects_hero_not_in_room(good_quest_4h, catalogs):
    game_state = _game_state((1, 1), ["R1", "R3"])
    with pytest.raises(InvalidTrapSearchError):
        resolve_trap_search(board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", room_id="R3")


def test_rejects_unrevealed_room(good_quest_4h, catalogs):
    game_state = _game_state((9, 5), [])
    with pytest.raises(InvalidTrapSearchError):
        resolve_trap_search(board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", room_id="R3")


def test_rejects_already_searched_room(good_quest_4h, catalogs):
    game_state = _game_state((9, 5), ["R3"], searched={"R3": {"traps": True}})
    with pytest.raises(InvalidTrapSearchError):
        resolve_trap_search(board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", room_id="R3")


def test_corridor_traps_out_of_scope(good_quest_4h, catalogs):
    # The fixture's corridorTraps entry must never surface from a room search.
    game_state = _game_state((9, 5), ["R3"])
    result = resolve_trap_search(board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian", room_id="R3")
    assert all(not t.trap_id.startswith("CORRIDOR") for t in result.found_traps)


def test_trap_search_does_not_reveal_secret_doors(good_quest_4h, catalogs):
    # Two DISTINCT hero actions (1989 rulebook, Actions 4 and 5) -- one
    # button doing both would hand the party a free action.
    game_state = _game_state((9, 5), ["R3"], doors={"D3": "secret"})
    result = resolve_trap_search(
        board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian",
        room_id="R3", search_type="traps",
    )
    assert result.found_secret_doors == []
    assert result.found_traps  # the room's trap is still found


def test_secret_door_search_does_not_reveal_traps(good_quest_4h, catalogs):
    game_state = _game_state((9, 5), ["R3"], doors={"D3": "secret"})
    result = resolve_trap_search(
        board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian",
        room_id="R3", search_type="secret_doors",
    )
    assert result.found_traps == []


def test_each_search_type_has_its_own_once_per_room_flag(good_quest_4h, catalogs):
    # Having searched for traps must not block a secret-door search.
    game_state = _game_state((9, 5), ["R3"], doors={"D3": "secret"}, searched={"R3": {"traps": True}})
    result = resolve_trap_search(
        board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian",
        room_id="R3", search_type="secret_doors",
    )
    assert len(result.found_secret_doors) == 1


def test_rejects_unknown_search_type(good_quest_4h, catalogs):
    game_state = _game_state((9, 5), ["R3"])
    with pytest.raises(InvalidTrapSearchError):
        resolve_trap_search(
            board=catalogs.board, quest=good_quest_4h, game_state=game_state, hero_id="barbarian",
            room_id="R3", search_type="treasure",
        )
