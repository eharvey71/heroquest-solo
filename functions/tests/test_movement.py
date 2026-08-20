"""Movement tests run against the real board.json data (via the shared
`catalogs` fixture), not a toy grid -- so a passing test means the A*
implementation actually works on the geometry the game will use, not
just an idealized abstraction of it.
"""

from engine.movement import (
    find_path,
    move_toward,
    passable_door_edges,
    revealed_squares,
    squares_adjacent_to,
)

# R1 (x:1-4,y:1-3) <-D1(4,1)/(5,1)-> R2 (x:5-8,y:1-3). Reused across tests.
D1 = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "closed"}


def _revealed(board):
    return revealed_squares(board, {"rooms": ["R1", "R2"], "corridorSquares": []})


def test_find_path_through_open_door(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    path = find_path(board, _revealed(board), edges, set(), (6, 2), {(2, 2)})
    assert path is not None
    assert path[0] == (6, 2)
    assert path[-1] == (2, 2)
    # every step is orthogonally adjacent to the last
    for a, b in zip(path, path[1:]):
        assert abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1


def test_find_path_blocked_by_closed_door(catalogs):
    # 1989 rulebook, "Monsters May Not: open or close doors" -- a closed
    # door is a wall to Zargon until the HEROES open it.
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "closed"})
    path = find_path(board, _revealed(board), edges, set(), (6, 2), {(2, 2)})
    assert path is None


def test_find_path_blocked_when_door_state_defaults(catalogs):
    # No override in door_states: the quest's declared state is used,
    # and a quest-declared "open" still means "starts closed" (see
    # engine/doors.effective_door_state), so it must not be passable.
    board = catalogs.board
    edges = passable_door_edges([D1], {})
    path = find_path(board, _revealed(board), edges, set(), (6, 2), {(2, 2)})
    assert path is None


def test_find_path_allowed_once_heroes_open_the_door(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    path = find_path(board, _revealed(board), edges, set(), (6, 2), {(2, 2)})
    assert path is not None


def test_find_path_respects_occupied_squares(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    # Block the only door square on the R2 side -- no other route exists
    # between R1 and R2 in this fixture, so the path must fail.
    occupied = {(5, 1)}
    path = find_path(board, _revealed(board), edges, occupied, (6, 2), {(2, 2)})
    assert path is None


def test_find_path_unreachable_outside_revealed_squares(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    # Target square is real (in R2) but not in the revealed set at all.
    revealed = revealed_squares(board, {"rooms": ["R1"], "corridorSquares": []})
    path = find_path(board, revealed, edges, set(), (2, 2), {(6, 2)})
    assert path is None


def test_find_path_picks_nearest_of_multiple_goals(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    goals = {(1, 1), (8, 3)}  # (1,1) is much closer to a (2,2) start
    path = find_path(board, _revealed(board), edges, set(), (2, 2), goals)
    assert path[-1] == (1, 1)


def test_squares_adjacent_to_is_four_orthogonal_neighbors():
    assert squares_adjacent_to((5, 5)) == {(6, 5), (4, 5), (5, 6), (5, 4)}


def test_move_toward_stops_adjacent_not_on_target(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    result = move_toward(board, _revealed(board), edges, set(), start=(6, 2), target=(2, 2), move_points=99)
    assert result is not None
    assert result.reachable_this_turn[-1] != (2, 2)
    assert result.reachable_this_turn[-1] in squares_adjacent_to((2, 2))
    assert result.reached_target_adjacency is True


def test_move_toward_truncates_to_move_points(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    full = move_toward(board, _revealed(board), edges, set(), start=(6, 2), target=(2, 2), move_points=99)
    partial = move_toward(board, _revealed(board), edges, set(), start=(6, 2), target=(2, 2), move_points=2)
    assert len(partial.reachable_this_turn) == 3  # start + 2 steps
    assert partial.reachable_this_turn == full.reachable_this_turn[:3]
    assert partial.reached_target_adjacency is False


def test_move_toward_zero_move_points_stays_put(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    result = move_toward(board, _revealed(board), edges, set(), start=(6, 2), target=(2, 2), move_points=0)
    assert result.reachable_this_turn == [(6, 2)]
    assert result.reached_target_adjacency is False


def test_move_toward_already_adjacent_needs_no_movement(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    result = move_toward(board, _revealed(board), edges, set(), start=(5, 2), target=(6, 2), move_points=5)
    assert result.reachable_this_turn == [(5, 2)]
    assert result.reached_target_adjacency is True


def test_move_toward_none_when_all_adjacent_squares_occupied(catalogs):
    board = catalogs.board
    edges = passable_door_edges([D1], {"D1": "open"})
    target = (2, 2)
    occupied = squares_adjacent_to(target)  # every approach square taken
    result = move_toward(board, _revealed(board), edges, occupied, start=(6, 2), target=target, move_points=99)
    assert result is None
