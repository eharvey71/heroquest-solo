"""Each test takes the known-good fixture and mutates exactly one thing,
so a failure here points at one check instead of forcing a diff against
a whole new hand-built quest.
"""

from validator.core import validate_quest
from validator.geometry import check_geometry


def errors_for(quest, catalogs):
    return check_geometry(quest, catalogs)


def test_unknown_room_id_rejected(good_quest_4h, catalogs):
    good_quest_4h["rooms"]["R99"] = good_quest_4h["rooms"].pop("R2")
    errors = errors_for(good_quest_4h, catalogs)
    assert any("R99 does not exist" in e for e in errors)


def test_unknown_monster_type_rejected(good_quest_4h, catalogs):
    good_quest_4h["rooms"]["R2"]["monsters"][0]["type"] = "beholder"
    errors = errors_for(good_quest_4h, catalogs)
    assert any("unknown type 'beholder'" in e for e in errors)


def test_unknown_furniture_type_rejected(good_quest_4h, catalogs):
    good_quest_4h["rooms"]["R3"]["furniture"][0]["type"] = "jukebox"
    errors = errors_for(good_quest_4h, catalogs)
    assert any("unknown furniture type 'jukebox'" in e for e in errors)


def test_monster_position_outside_room_rejected(good_quest_4h, catalogs):
    # (10, 1) is a real board square but belongs to R3, not R2.
    good_quest_4h["rooms"]["R2"]["monsters"][0]["pos"] = [10, 1]
    errors = errors_for(good_quest_4h, catalogs)
    assert any("is outside R2" in e for e in errors)


def test_furniture_footprint_hanging_outside_room_rejected(good_quest_4h, catalogs):
    # Move the tomb (3x2) so part of its footprint spills past R12's edge.
    good_quest_4h["rooms"]["R12"]["furniture"][0]["pos"] = [3, 12]
    errors = errors_for(good_quest_4h, catalogs)
    assert any("doesn't fit inside R12" in e for e in errors)


def test_overlapping_entities_rejected(good_quest_4h, catalogs):
    good_quest_4h["rooms"]["R2"]["monsters"][1]["pos"] = good_quest_4h["rooms"]["R2"]["monsters"][0]["pos"]
    errors = errors_for(good_quest_4h, catalogs)
    assert any("overlaps" in e for e in errors)


def test_stairway_footprint_outside_room_rejected(good_quest_4h, catalogs):
    # (4, 1) is inside R1, but the 2x2 footprint from there spills into R2.
    good_quest_4h["stairway"]["pos"] = [4, 1]
    errors = errors_for(good_quest_4h, catalogs)
    assert any("stairway at [4,1] is outside R1" in e for e in errors)


def test_missing_stairway_rejected(good_quest_4h, catalogs):
    del good_quest_4h["stairway"]
    errors = errors_for(good_quest_4h, catalogs)
    assert any("missing a stairway" in e for e in errors)


def test_door_not_adjacent_rejected(good_quest_4h, catalogs):
    good_quest_4h["doors"][0]["squares"] = [[4, 1], [9, 9]]
    errors = errors_for(good_quest_4h, catalogs)
    assert any("not orthogonally adjacent" in e for e in errors)


def test_door_within_same_room_rejected(good_quest_4h, catalogs):
    # Both squares are real, adjacent, and inside R1 — not a wall edge.
    good_quest_4h["doors"][0]["squares"] = [[1, 1], [2, 1]]
    errors = errors_for(good_quest_4h, catalogs)
    assert any("doesn't separate two areas" in e for e in errors)


def test_door_between_two_corridor_squares_rejected(good_quest_4h, catalogs):
    good_quest_4h["doors"][0]["squares"] = [[0, 0], [1, 0]]
    errors = errors_for(good_quest_4h, catalogs)
    assert any("doesn't separate two areas" in e for e in errors)


def test_missing_pos_reported_not_crashed(good_quest_4h, catalogs):
    del good_quest_4h["rooms"]["R2"]["monsters"][0]["pos"]
    errors = errors_for(good_quest_4h, catalogs)  # must not raise
    assert any("missing or malformed 'pos'" in e for e in errors)


def test_trap_position_outside_room_rejected(good_quest_4h, catalogs):
    # (10, 1) is a real board square but belongs to R3, not R5.
    good_quest_4h["rooms"]["R5"]["traps"] = [{"type": "pit", "pos": [10, 1]}]
    errors = errors_for(good_quest_4h, catalogs)
    assert any("is outside R5" in e for e in errors)


def test_corridor_trap_outside_corridor_rejected(good_quest_4h, catalogs):
    good_quest_4h["corridorTraps"][0]["pos"] = [2, 1]  # a real R1 square
    errors = errors_for(good_quest_4h, catalogs)
    assert any("is not a corridor square" in e for e in errors)


def test_good_quest_end_to_end_still_clean(good_quest_4h, good_quest_4h_params, catalogs):
    # Guards against a mutation test accidentally not deep-copying.
    result = validate_quest(good_quest_4h, good_quest_4h_params, catalogs)
    assert result.ok
