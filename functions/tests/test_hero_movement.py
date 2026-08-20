"""Hero movement resolution tests, against real board.json geometry.

R1 (x:1-4,y:1-3) <-D1(4,1)/(5,1)-> R2 (x:5-8,y:1-3), same fixture door
used across the engine test suite. (3,0)/(4,0)/(5,0) are real corridor
squares north of R1/R2 (verified against board.json).
"""

import pytest

from engine.hero_movement import IllegalMovementError, resolve_hero_movement

D1 = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "closed"}


def _quest(**overrides):
    quest = {"doors": [D1], "blockedSquares": [], "rooms": {}, "corridorTraps": []}
    quest.update(overrides)
    return quest


def _game_state(**overrides):
    state = {
        "heroes": [{"id": "barbarian", "pos": [2, 2], "active": True}],
        "monsters": {},
        "revealed": {"rooms": ["R1"], "corridorSquares": []},
        "doors": {"D1": "open"},
        "trapsTriggered": [],
    }
    state.update(overrides)
    return state


def test_full_path_through_open_door_reveals_room(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state()
    path = [[2, 2], [3, 2], [4, 2], [4, 1], [5, 1], [6, 1], [6, 2]]

    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=path)

    assert result.final_pos == (6, 2)
    assert result.stopped_reason is None
    assert result.newly_revealed_rooms == ["R2"]
    assert "R2" in result.revealed_rooms
    assert result.path_taken == [tuple(p) for p in path]


def test_pit_trap_ends_the_move_on_the_trap_square(catalogs):
    # 1989 rulebook: springing a pit "ends your turn", and the tile goes
    # under the hero's figure -- so the hero ends ON the trap square.
    board = catalogs.board
    quest = _quest(rooms={"R2": {"traps": [{"type": "pit", "pos": [6, 1]}]}})
    game_state = _game_state()
    path = [[2, 2], [3, 2], [4, 2], [4, 1], [5, 1], [6, 1], [6, 2]]

    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=path)

    assert result.stopped_reason == "trap_sprung"
    assert result.final_pos == (6, 1)
    assert len(result.triggered_traps) == 1
    trap = result.triggered_traps[0]
    assert trap.trap_id == "R2-T1"
    assert trap.trap_type == "pit"
    assert trap.pos == (6, 1)
    assert "R2-T1" in result.traps_triggered
    assert result.collapsed_squares == set()  # a pit is not a permanent block


def test_falling_block_seals_the_square_and_the_hero_stays_back(catalogs):
    # The ceiling comes down before the hero is through: they never take
    # the square, and it is blocked for the rest of the quest.
    board = catalogs.board
    quest = _quest(rooms={"R2": {"traps": [{"type": "falling_block", "pos": [6, 1]}]}})
    game_state = _game_state()
    path = [[2, 2], [3, 2], [4, 2], [4, 1], [5, 1], [6, 1], [6, 2]]

    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=path)

    assert result.stopped_reason == "trap_sprung"
    assert result.final_pos == (5, 1)  # stopped short of the collapse
    assert (6, 1) in result.collapsed_squares
    assert result.triggered_traps[0].trap_type == "falling_block"


def test_collapsed_square_blocks_later_movement(catalogs):
    board = catalogs.board
    quest = _quest(rooms={"R2": {"traps": []}})
    game_state = _game_state(collapsedSquares=[[5, 1]])
    path = [[2, 2], [3, 2], [4, 2], [4, 1], [5, 1]]

    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=path)

    assert result.stopped_reason == "blocked_square"
    assert result.final_pos == (4, 1)


def test_already_triggered_trap_does_not_refire(catalogs):
    board = catalogs.board
    quest = _quest(rooms={"R2": {"traps": [{"type": "pit", "pos": [6, 1]}]}})
    game_state = _game_state(trapsTriggered=["R2-T1"])
    path = [[2, 2], [3, 2], [4, 2], [4, 1], [5, 1], [6, 1]]

    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=path)

    assert result.triggered_traps == []


def test_stops_at_closed_door_threshold(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state(doors={"D1": "closed"})
    path = [[2, 2], [3, 2], [4, 2], [4, 1], [5, 1], [6, 1]]

    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=path)

    assert result.final_pos == (4, 1)
    assert result.stopped_reason == "closed_door"
    assert result.stopped_at_door_id == "D1"
    assert result.newly_revealed_rooms == []


def test_stops_before_a_monster(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state(monsters={"M1": {"pos": [5, 1], "currentBody": 1, "alive": True}})
    path = [[2, 2], [3, 2], [4, 2], [4, 1], [5, 1], [6, 1]]

    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=path)

    assert result.final_pos == (4, 1)
    assert result.stopped_reason == "monster_blocked"


def test_dead_monster_does_not_block(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state(monsters={"M1": {"pos": [5, 1], "currentBody": 0, "alive": False}})
    path = [[2, 2], [3, 2], [4, 2], [4, 1], [5, 1], [6, 1]]

    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=path)

    assert result.final_pos == (6, 1)
    assert result.stopped_reason is None


def test_stops_before_a_blocked_square(catalogs):
    board = catalogs.board
    quest = _quest(blockedSquares=[[3, 2]])
    game_state = _game_state()
    path = [[2, 2], [3, 2], [4, 2]]

    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=path)

    assert result.final_pos == (2, 2)
    assert result.stopped_reason == "blocked_square"


def test_corridor_is_revealed_by_line_of_sight(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state(
        heroes=[{"id": "barbarian", "pos": [3, 0], "active": True}],
        revealed={"rooms": [], "corridorSquares": [[3, 0]]},
    )
    path = [[3, 0], [4, 0], [5, 0]]

    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=path)

    assert result.final_pos == (5, 0)
    # Every square walked is revealed...
    assert {(4, 0), (5, 0)} <= result.revealed_corridor_squares
    # ...and so is corridor the hero could SEE along the way, which is
    # the whole point: the party looks down a corridor, it doesn't
    # discover it one square at a time.
    assert len(result.revealed_corridor_squares) > len(path)
    # But sight stops at walls -- never the entire corridor network.
    assert len(result.revealed_corridor_squares) < len(board.corridor_squares)


def test_rejects_path_not_starting_at_hero_position(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state()
    with pytest.raises(IllegalMovementError):
        resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=[[3, 2], [4, 2]])


def test_rejects_non_adjacent_step(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state()
    with pytest.raises(IllegalMovementError):
        resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=[[2, 2], [4, 4]])


def test_rejects_unknown_hero(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state()
    with pytest.raises(IllegalMovementError):
        resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="wizard", path=[[2, 2]])


def test_rejects_ending_on_another_heros_square(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state(
        heroes=[
            {"id": "barbarian", "pos": [2, 2], "active": True},
            {"id": "wizard", "pos": [3, 2], "active": True},
        ]
    )
    with pytest.raises(IllegalMovementError):
        resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=[[2, 2], [3, 2]])


def test_heroes_may_pass_through_each_other_but_not_end_there(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state(
        heroes=[
            {"id": "barbarian", "pos": [2, 2], "active": True},
            {"id": "wizard", "pos": [3, 2], "active": True},
        ]
    )
    # passes through wizard's square (3,2) but ends elsewhere -- legal
    result = resolve_hero_movement(
        board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian",
        path=[[2, 2], [3, 2], [4, 2]]
    )
    assert result.final_pos == (4, 2)
    assert result.stopped_reason is None


def test_single_square_path_is_a_no_op(catalogs):
    board = catalogs.board
    quest = _quest()
    game_state = _game_state()
    result = resolve_hero_movement(board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian", path=[[2, 2]])
    assert result.final_pos == (2, 2)
    assert result.path_taken == [(2, 2)]
    assert result.stopped_reason is None


def test_furniture_blocks_movement(catalogs):
    # A bookcase (3x1) anchored at (3,2) covers (3,2)-(5,2); the hero at
    # (2,2) can't walk onto it -- furniture is solid on the real board.
    board = catalogs.board
    quest = _quest(rooms={"R1": {"furniture": [{"type": "bookcase", "pos": [3, 2], "orientation": "N"}]}})
    game_state = _game_state()
    result = resolve_hero_movement(
        board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian",
        path=[[2, 2], [3, 2], [4, 2]]
    )
    assert result.stopped_reason == "furniture_blocked"
    assert result.final_pos == (2, 2)  # partial credit: stopped before the piece


def test_movement_around_furniture_is_fine(catalogs):
    board = catalogs.board
    quest = _quest(rooms={"R1": {"furniture": [{"type": "bookcase", "pos": [3, 2], "orientation": "N"}]}})
    game_state = _game_state()
    result = resolve_hero_movement(
        board=board, catalogs=catalogs, quest=quest, game_state=game_state, hero_id="barbarian",
        path=[[2, 2], [2, 1], [3, 1]]
    )
    assert result.stopped_reason is None
    assert result.final_pos == (3, 1)


def test_a_fallen_hero_cannot_move(catalogs):
    quest = _quest()
    game_state = _game_state()
    game_state["heroes"][0]["alive"] = False
    with pytest.raises(IllegalMovementError):
        resolve_hero_movement(
            board=catalogs.board, catalogs=catalogs, quest=quest, game_state=game_state,
            hero_id=game_state["heroes"][0]["id"], path=[game_state["heroes"][0]["pos"]],
        )


def test_a_fallen_heros_square_can_be_walked_over(catalogs):
    # Heroes may pass through fellow heroes anyway; what matters is that
    # the square is free to END on, which a living hero's never is.
    quest = _quest()
    game_state = _game_state()
    mover = game_state["heroes"][0]
    start = tuple(mover["pos"])
    game_state["heroes"].append(
        {"id": "elf", "name": "Elf", "pos": [start[0] + 1, start[1]], "alive": False}
    )

    result = resolve_hero_movement(
        board=catalogs.board, catalogs=catalogs, quest=quest, game_state=game_state,
        hero_id=mover["id"], path=[list(start), [start[0] + 1, start[1]]],
    )
    assert result.final_pos == (start[0] + 1, start[1])
    assert result.stopped_reason is None
