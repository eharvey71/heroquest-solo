"""Line-of-sight tests against real board.json geometry.

R1 (x:1-4, y:1-3) <-D1(4,1)/(5,1)-> R2 (x:5-8, y:1-3).
(3,0)/(4,0)/(5,0) are corridor squares north of R1/R2.
"""

from engine.line_of_sight import has_line_of_sight, visible_corridor_squares

D1_EDGE = frozenset(((4, 1), (5, 1)))


def test_clear_line_inside_one_room(catalogs):
    assert has_line_of_sight(catalogs.board, (1, 1), (4, 3), open_door_edges=set())


def test_a_wall_between_two_rooms_blocks_sight(catalogs):
    assert not has_line_of_sight(catalogs.board, (4, 1), (5, 1), open_door_edges=set())


def test_an_open_door_lets_sight_through(catalogs):
    assert has_line_of_sight(catalogs.board, (4, 1), (5, 1), open_door_edges={D1_EDGE})


def test_a_closed_door_does_not(catalogs):
    # Same geometry, but the edge isn't in the open set.
    assert not has_line_of_sight(catalogs.board, (3, 1), (6, 1), open_door_edges=set())


def test_a_blocked_square_blocks_sight(catalogs):
    assert not has_line_of_sight(
        catalogs.board, (1, 1), (4, 1), open_door_edges=set(), walls=frozenset({(2, 1)})
    )


def test_a_figure_blocks_targeting(catalogs):
    assert not has_line_of_sight(
        catalogs.board, (1, 1), (4, 1), open_door_edges=set(), figures=frozenset({(2, 1)})
    )


def test_a_figure_does_not_block_when_revealing(catalogs):
    # Revealing passes no figures: terrain once seen stays seen.
    assert has_line_of_sight(catalogs.board, (1, 1), (4, 1), open_door_edges=set())


def test_neither_endpoint_blocks_itself(catalogs):
    # The target square holding a monster is exactly what we're looking at.
    assert has_line_of_sight(
        catalogs.board, (1, 1), (4, 1), open_door_edges=set(),
        figures=frozenset({(1, 1), (4, 1)}),
    )


def test_sight_is_symmetric(catalogs):
    board = catalogs.board
    a, b = (1, 1), (4, 3)
    assert has_line_of_sight(board, a, b, open_door_edges=set()) == has_line_of_sight(
        board, b, a, open_door_edges=set()
    )


def test_a_hero_sees_only_part_of_the_corridor_network(catalogs):
    # Sanity: standing in one corridor square must not reveal all 148.
    seen = visible_corridor_squares(catalogs.board, (3, 0), open_door_edges=set())
    assert (3, 0) in seen
    assert 0 < len(seen) < len(catalogs.board.corridor_squares)


def test_a_hero_inside_a_room_sees_no_corridor_through_a_closed_door(catalogs):
    seen = visible_corridor_squares(catalogs.board, (2, 2), open_door_edges=set())
    assert seen == set()
