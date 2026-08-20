import random

import pytest

from engine.movement import passable_door_edges, revealed_squares
from engine.turn import take_monster_turn

D1 = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "closed"}


def _setup(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    revealed = revealed_squares(board, {"rooms": ["R1", "R2"], "corridorSquares": []})
    return board, edges, revealed


def test_monster_reaches_and_attacks_with_enough_move_points(catalogs):
    board, edges, revealed = _setup(catalogs)
    result = take_monster_turn(
        board=board,
        revealed=revealed,
        door_edges=edges,
        occupied=set(),
        monster_id="M1",
        monster_name="Orc",
        monster_pos=(6, 2),
        move_points=10,
        attack_dice=3,
        target_hero_id="barbarian",
        target_hero_name="Barbarian",
        target_hero_pos=(2, 2),
        rng=random.Random(5),
    )
    assert result.moved is True
    assert result.attacked is True
    assert result.attack is not None
    assert result.end_pos != (6, 2)


def test_monster_moves_partway_without_reaching_range(catalogs):
    board, edges, revealed = _setup(catalogs)
    result = take_monster_turn(
        board=board,
        revealed=revealed,
        door_edges=edges,
        occupied=set(),
        monster_id="M1",
        monster_name="Orc",
        monster_pos=(6, 2),
        move_points=2,
        attack_dice=3,
        target_hero_id="barbarian",
        target_hero_name="Barbarian",
        target_hero_pos=(2, 2),
        rng=random.Random(5),
    )
    assert result.moved is True
    assert result.attacked is False
    assert result.attack is None


def test_monster_already_adjacent_attacks_without_moving(catalogs):
    board, edges, revealed = _setup(catalogs)
    result = take_monster_turn(
        board=board,
        revealed=revealed,
        door_edges=edges,
        occupied=set(),
        monster_id="M1",
        monster_name="Orc",
        monster_pos=(5, 2),
        move_points=10,
        attack_dice=3,
        target_hero_id="barbarian",
        target_hero_name="Barbarian",
        target_hero_pos=(6, 2),
        rng=random.Random(5),
    )
    assert result.moved is False
    assert result.end_pos == (5, 2)
    assert result.attacked is True


def test_guarding_monster_holds_position_when_hero_cannot_see_the_room(catalogs):
    board, edges, revealed = _setup(catalogs)
    result = take_monster_turn(
        board=board,
        revealed=revealed,
        door_edges=edges,
        occupied=set(),
        monster_id="M1",
        monster_name="Orc",
        monster_pos=(6, 2),  # in R2
        move_points=10,
        attack_dice=3,
        target_hero_id="barbarian",
        target_hero_name="Barbarian",
        target_hero_pos=(2, 2),  # deep in R1, not at the R2 doorway
        guarding=True,
        monster_room_id="R2",
        heroes=[{"id": "barbarian", "pos": [2, 2]}],
        rng=random.Random(5),
    )
    assert result.moved is False
    assert result.attacked is False
    assert result.end_pos == (6, 2)


def test_guarding_monster_wakes_and_chases_once_hero_enters_room(catalogs):
    # The fix this test locks in: a hero can walk into a guard's room and
    # search it without ever touching the guard's exact square -- the
    # old "must be adjacent" trigger let that go unnoticed. Room entry
    # alone must wake it, even from clear across the room.
    board, edges, revealed = _setup(catalogs)
    result = take_monster_turn(
        board=board,
        revealed=revealed,
        door_edges=edges,
        occupied=set(),
        monster_id="M1",
        monster_name="Orc",
        monster_pos=(8, 3),  # far corner of R2
        move_points=10,
        attack_dice=3,
        target_hero_id="barbarian",
        target_hero_name="Barbarian",
        target_hero_pos=(5, 2),  # just stepped into R2, nowhere near (8,3)
        guarding=True,
        monster_room_id="R2",
        heroes=[{"id": "barbarian", "pos": [5, 2]}],
        rng=random.Random(5),
    )
    assert result.moved is True
    assert result.end_pos != (8, 3)


def test_guarding_monster_still_fights_when_already_adjacent(catalogs):
    board, edges, revealed = _setup(catalogs)
    result = take_monster_turn(
        board=board,
        revealed=revealed,
        door_edges=edges,
        occupied=set(),
        monster_id="M1",
        monster_name="Orc",
        monster_pos=(5, 2),
        move_points=10,
        attack_dice=3,
        target_hero_id="barbarian",
        target_hero_name="Barbarian",
        target_hero_pos=(6, 2),
        guarding=True,
        monster_room_id="R2",
        heroes=[{"id": "barbarian", "pos": [6, 2]}],
        rng=random.Random(5),
    )
    assert result.moved is False
    assert result.attacked is True


def test_guarding_requires_monster_room_id_and_heroes():
    with pytest.raises(ValueError):
        take_monster_turn(
            board=None,
            revealed=set(),
            door_edges=set(),
            occupied=set(),
            monster_id="M1",
            monster_name="Orc",
            monster_pos=(6, 2),
            move_points=10,
            attack_dice=3,
            target_hero_id="barbarian",
            target_hero_name="Barbarian",
            target_hero_pos=(2, 2),
            guarding=True,
        )


def test_monster_with_no_path_does_not_crash(catalogs):
    board, _edges, revealed = _setup(catalogs)
    closed_edges = passable_door_edges([D1], {"D1": "closed"})
    result = take_monster_turn(
        board=board,
        revealed=revealed,
        door_edges=closed_edges,
        occupied=set(),
        monster_id="M1",
        monster_name="Orc",
        monster_pos=(6, 2),
        move_points=10,
        attack_dice=3,
        target_hero_id="barbarian",
        target_hero_name="Barbarian",
        target_hero_pos=(2, 2),
        rng=random.Random(5),
    )
    assert result.moved is False
    assert result.attacked is False
    assert "no path" in result.log[0]
