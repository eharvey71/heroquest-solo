from firestore_coords import from_firestore_coords, to_firestore_coords


def test_simple_pair_round_trips():
    assert to_firestore_coords([4, 1]) == {"x": 4, "y": 1}
    assert from_firestore_coords({"x": 4, "y": 1}) == [4, 1]


def test_array_of_pairs_becomes_array_of_maps():
    squares = [[4, 1], [5, 1]]
    stored = to_firestore_coords(squares)
    assert stored == [{"x": 4, "y": 1}, {"x": 5, "y": 1}]
    assert from_firestore_coords(stored) == squares


def test_nested_door_object_round_trips():
    door = {"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"}
    stored = to_firestore_coords(door)
    assert stored == {"id": "D1", "squares": [{"x": 4, "y": 1}, {"x": 5, "y": 1}], "state": "open"}
    assert from_firestore_coords(stored) == door


def test_full_quest_shape_round_trips(good_quest_4h):
    stored = to_firestore_coords(good_quest_4h)
    restored = from_firestore_coords(stored)
    assert restored == good_quest_4h


def test_non_coordinate_fields_untouched():
    quest = {"title": "The Trial", "wanderingMonster": "orc", "attempts": 3}
    assert to_firestore_coords(quest) == quest
    assert from_firestore_coords(quest) == quest


def test_empty_list_untouched():
    assert to_firestore_coords([]) == []
    assert from_firestore_coords([]) == []


def test_tuple_coord_converts_like_a_list():
    # Engine coords are tuples (Coord = tuple[int, int]); an unconverted
    # tuple reaches Firestore as a nested array and the write fails.
    assert to_firestore_coords((4, 1)) == {"x": 4, "y": 1}


def test_list_of_tuple_coords_converts_elementwise():
    # revealed.corridorSquares is written as sorted(set-of-tuples) --
    # this is the party's-first-corridor-step path that failed INTERNAL.
    assert to_firestore_coords([(12, 15), (13, 15)]) == [{"x": 12, "y": 15}, {"x": 13, "y": 15}]


def test_no_python_tuples_survive_conversion():
    converted = to_firestore_coords({"revealed": {"corridorSquares": [(1, 2), (3, 4)]}})
    squares = converted["revealed"]["corridorSquares"]
    assert all(isinstance(sq, dict) for sq in squares)


def test_tuple_round_trips_back_to_list_form():
    assert from_firestore_coords(to_firestore_coords((7, 9))) == [7, 9]
