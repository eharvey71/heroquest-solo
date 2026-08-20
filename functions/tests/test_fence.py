"""The cordon that keeps a 4-room quest from becoming a 148-square
corridor crawl. See generator/fence.py.
"""

from generator.fence import apply_fence, compute_fence
from validator.balance import BLOCKED_SQUARE_CAP, blocked_squares_fit_tiles
from validator.catalogs import CORRIDOR
from validator.core import validate_quest
from validator.geometry import footprint_cells
from validator.reachability import NON_SECRET_STATES, _bfs, _door_edges


def walkable(quest, catalogs, blocked=()):
    board = catalogs.board
    edges = _door_edges(quest, NON_SECRET_STATES | {"secret"})
    start = footprint_cells(tuple(quest["stairway"]["pos"]), (2, 2))
    return _bfs(board, start, edges, {tuple(sq) for sq in blocked})


def corridor_count(board, squares):
    return sum(1 for sq in squares if board.area_of.get(sq) == CORRIDOR)


def test_fence_seals_the_corridors_the_quest_never_uses(good_quest_4h, catalogs):
    good_quest_4h["blockedSquares"] = []
    fence = compute_fence(good_quest_4h, catalogs)
    assert fence

    before = corridor_count(catalogs.board, walkable(good_quest_4h, catalogs))
    after = corridor_count(catalogs.board, walkable(good_quest_4h, catalogs, fence))
    # 5 populated rooms in one corner of the board: most of the corridor
    # network is nothing but walking.
    assert before == 148
    assert after < before / 4


def test_fence_keeps_every_populated_room_and_the_objective_reachable(good_quest_4h, catalogs):
    fence = compute_fence(good_quest_4h, catalogs)
    reached = walkable(good_quest_4h, catalogs, fence)
    for room_id in good_quest_4h["rooms"]:
        assert catalogs.board.room_squares[room_id] <= reached, f"{room_id} was fenced off"


def test_fence_never_stands_on_a_door_edge(good_quest_4h, catalogs):
    fence = set(compute_fence(good_quest_4h, catalogs))
    for door in good_quest_4h["doors"]:
        for square in door["squares"]:
            assert tuple(square) not in fence


def test_fence_leaves_corridor_traps_reachable(good_quest_4h, catalogs):
    # A trap out in the corridor is content the party is meant to find,
    # so the cordon has to be drawn outside it.
    good_quest_4h["corridorTraps"] = [{"id": "CT1", "type": "pit", "pos": [12, 6]}]
    fence = compute_fence(good_quest_4h, catalogs)
    assert (12, 6) in walkable(good_quest_4h, catalogs, fence)
    assert (12, 6) not in set(fence)


def test_fence_only_ever_tiles_corridor_squares(good_quest_4h, catalogs):
    for square in compute_fence(good_quest_4h, catalogs):
        assert catalogs.board.area_of[square] == CORRIDOR


def test_fence_fits_the_tiles_in_the_box(good_quest_4h, catalogs):
    fence = compute_fence(good_quest_4h, catalogs)
    assert len(fence) <= BLOCKED_SQUARE_CAP
    assert blocked_squares_fit_tiles(fence)


def test_no_fence_when_the_quest_reaches_no_corridor(good_quest_1h, catalogs):
    # This quest's rooms open only into each other -- there is no
    # corridor roaming to prevent, so no tile should be spent.
    assert corridor_count(catalogs.board, walkable(good_quest_1h, catalogs)) == 0
    assert compute_fence(good_quest_1h, catalogs) == []


def test_fence_is_deterministic(good_quest_4h, catalogs):
    assert compute_fence(good_quest_4h, catalogs) == compute_fence(good_quest_4h, catalogs)


def test_apply_fence_replaces_whatever_the_model_declared(good_quest_4h, catalogs):
    good_quest_4h["blockedSquares"] = [[3, 3]]
    fence = apply_fence(good_quest_4h, catalogs)
    assert good_quest_4h["blockedSquares"] == [list(sq) for sq in fence]
    assert [3, 3] not in good_quest_4h["blockedSquares"]


def test_fenced_quest_still_validates(good_quest_4h, good_quest_4h_params, catalogs):
    apply_fence(good_quest_4h, catalogs)
    result = validate_quest(good_quest_4h, good_quest_4h_params, catalogs)
    assert result.ok, result.errors


def test_a_malformed_stairway_fences_nothing(good_quest_4h, catalogs):
    good_quest_4h["stairway"] = {"room": "R99"}
    assert compute_fence(good_quest_4h, catalogs) == []


def _synthetic_quest(catalogs, rooms):
    """A minimal quest: each room gets a door onto the corridor network,
    the stairway sits in the first one. Enough for the fence, which
    only reads geometry -- monsters and story don't move a graph cut.
    """
    board = catalogs.board
    doors = []
    for i, room_id in enumerate(rooms):
        for square in sorted(board.room_squares[room_id]):
            neighbours = [
                (square[0] + dx, square[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            ]
            corridor = next((n for n in neighbours if board.area_of.get(n) == CORRIDOR), None)
            if corridor:
                doors.append({"id": f"D{i}", "squares": [list(square), list(corridor)], "state": "closed"})
                break
    stair_room = board.room_squares[rooms[0]]
    stair_pos = next(
        (x, y) for x, y in sorted(stair_room)
        if {(x + 1, y), (x, y + 1), (x + 1, y + 1)} <= stair_room
    )
    return {
        "stairway": {"room": rooms[0], "pos": list(stair_pos)},
        "rooms": {r: {"monsters": [], "furniture": [], "traps": []} for r in rooms[1:]},
        "doors": doors,
        "corridorTraps": [],
        "blockedSquares": [],
        "objective": {"type": "kill_boss", "target": {"room": rooms[-1]}},
    }


LAYOUTS = [
    ["R1", "R2", "R5", "R4"],          # one corner
    ["R1", "R22", "R11"],              # opposite corners
    ["R6", "R7", "R8", "R9", "R10"],   # one band
    ["R3", "R11", "R19", "R14"],       # spread across the middle
    ["R1", "R2"],                      # as small as a quest gets
]


def test_every_layout_gets_a_fence_that_holds_its_invariants(catalogs):
    for rooms in LAYOUTS:
        quest = _synthetic_quest(catalogs, rooms)
        fence = compute_fence(quest, catalogs)
        assert fence, f"no fence for {rooms}"
        assert len(fence) <= BLOCKED_SQUARE_CAP and blocked_squares_fit_tiles(fence), rooms

        reached = walkable(quest, catalogs, fence)
        for room_id in rooms:
            assert catalogs.board.room_squares[room_id] <= reached, f"{room_id} fenced off in {rooms}"
        for door in quest["doors"]:
            for square in door["squares"]:
                assert tuple(square) in reached, f"door stranded in {rooms}"
        # The point of the exercise: the party can no longer walk the
        # whole corridor network looking for rooms that aren't used.
        assert corridor_count(catalogs.board, reached) < 148 / 2, rooms
