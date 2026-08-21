import random

import pytest

from engine.movement import passable_door_edges, revealed_squares
from engine.movement import squares_adjacent_to
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


# ---- attack then move (1989: move-then-act OR act-then-move) ----

def _contact_setup(catalogs, extra_heroes=()):
    """Orc at (6,2) in R2 (x:5-8, y:1-3), hero already adjacent at (5,2)."""
    board = catalogs.board
    revealed = set(board.room_squares["R2"]) | set(board.room_squares["R1"])
    heroes = [{"id": "barbarian", "name": "Barbarian", "pos": [5, 2], "alive": True}, *extra_heroes]
    hero_squares = {tuple(h["pos"]) for h in heroes}
    return board, revealed, heroes, hero_squares


def _take(board, revealed, hero_squares, policy, pos=(6, 2), move_points=8, occupied=None):
    return take_monster_turn(
        board=board,
        revealed=revealed,
        door_edges=set(),
        occupied=(occupied if occupied is not None else set(hero_squares)) | {pos},
        monster_id="M1",
        monster_name="Grukk",
        monster_pos=pos,
        move_points=move_points,
        attack_dice=3,
        target_hero_id="barbarian",
        target_hero_name="Barbarian",
        target_hero_pos=(5, 2),
        hero_squares=hero_squares,
        withdraw_policy=policy,
        rng=random.Random(1),
    )


def test_policy_none_keeps_the_old_behaviour(catalogs):
    board, revealed, _, hero_squares = _contact_setup(catalogs)
    result = _take(board, revealed, hero_squares, "none")
    assert result.attacked is True
    assert result.withdrew is False
    assert result.end_pos == (6, 2)


def test_reposition_policy_never_breaks_contact(catalogs):
    # Flanked: heroes at (5,2) and (6,1). Stepping to (7,2) keeps the
    # Barbarian in reach while shaking the second attacker off.
    board, revealed, _, hero_squares = _contact_setup(
        catalogs, extra_heroes=[{"id": "elf", "name": "Elf", "pos": [6, 1], "alive": True}]
    )
    result = _take(board, revealed, hero_squares, "reposition")

    assert result.attacked is True
    assert result.withdrew is True
    assert len(squares_adjacent_to(result.end_pos) & hero_squares) == 1
    assert squares_adjacent_to(result.end_pos) & hero_squares  # still fighting someone


def test_reposition_policy_holds_when_moving_buys_nothing(catalogs):
    # One hero, one attacker: every adjacent square is equally exposed,
    # so the monster should stand its ground rather than shuffle.
    board, revealed, _, hero_squares = _contact_setup(catalogs)
    result = _take(board, revealed, hero_squares, "reposition")
    assert result.withdrew is False
    assert result.end_pos == (6, 2)


def test_fall_back_policy_steps_out_of_reach(catalogs):
    board, revealed, _, hero_squares = _contact_setup(catalogs)
    result = _take(board, revealed, hero_squares, "fall_back")

    assert result.attacked is True
    assert result.withdrew is True
    assert not (squares_adjacent_to(result.end_pos) & hero_squares)  # out of reach
    # Out of reach, but only just -- a monster that sprints to the far
    # wall after every swing looks absurd on the table.
    assert abs(result.end_pos[0] - 6) + abs(result.end_pos[1] - 2) <= 2


def test_a_monster_that_had_to_walk_in_does_not_also_withdraw(catalogs):
    # The rulebook allows move-then-act or act-then-move, never
    # move-part-way, act, move again.
    board, revealed, _, hero_squares = _contact_setup(catalogs)
    result = _take(board, revealed, hero_squares, "fall_back", pos=(8, 2))

    assert result.moved is True
    assert result.withdrew is False


def test_a_guard_never_withdraws(catalogs):
    board, revealed, heroes, hero_squares = _contact_setup(catalogs)
    result = take_monster_turn(
        board=board,
        revealed=revealed,
        door_edges=set(),
        occupied=set(hero_squares) | {(6, 2)},
        monster_id="M1",
        monster_name="Grukk",
        monster_pos=(6, 2),
        move_points=8,
        attack_dice=3,
        target_hero_id="barbarian",
        target_hero_name="Barbarian",
        target_hero_pos=(5, 2),
        guarding=True,
        monster_room_id="R2",
        heroes=heroes,
        hero_squares=hero_squares,
        withdraw_policy="fall_back",
        rng=random.Random(1),
    )
    assert result.withdrew is False
    assert result.end_pos == (6, 2)


def test_unknown_policy_rejected(catalogs):
    board, revealed, _, hero_squares = _contact_setup(catalogs)
    with pytest.raises(ValueError):
        _take(board, revealed, hero_squares, "flee-always")
