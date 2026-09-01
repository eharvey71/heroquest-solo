"""lastMoves: the squares a figure walked in the action just written,
so the client can step the token along the board's actual corridors
instead of sliding it straight through a wall. Fake Firestore, same
conventions as test_main_defence_queue.py.
"""

import copy

import main
from firestore_coords import from_firestore_coords, to_firestore_coords

QUEST = {
    "doors": [{"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"}],
    "objective": {"type": "kill_boss", "description": "x", "target": {"room": "R2"}},
    "wanderingMonster": "orc",
    "rooms": {
        "R2": {
            "monsters": [{"id": "M1", "type": "orc", "name": "", "pos": [8, 3]}],
            "traps": [{"type": "pit", "pos": [7, 3]}],
            "furniture": [],
        }
    },
    "stairway": {"room": "R1", "pos": [1, 1]},
}

GAME = {
    "questId": "Q1",
    "phase": "hero",
    "status": "in_progress",
    "turn": 3,
    "heroes": [{"id": "barbarian", "name": "Barbarian", "pos": [6, 2], "active": True}],
    "monsters": {"M1": {"pos": [8, 3], "currentBody": 1, "alive": True}},
    "revealed": {"rooms": ["R1", "R2"], "corridorSquares": []},
    "doors": {"D1": "open"},
    "log": [],
    "undoDepth": 0,
}


class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self._data)


class _Ref:
    def __init__(self, data):
        self._data = data

    def get(self, transaction=None):
        return _Snap(self._data)

    def collection(self, name):
        return _Coll({})


class _Coll:
    def __init__(self, docs):
        self._docs = docs

    def document(self, name):
        return _Ref(self._docs.get(name))


class _DB:
    def collection(self, name):
        return _Coll({"Q1": to_firestore_coords(copy.deepcopy(QUEST))})


class _Txn:
    def __init__(self):
        self.updates = None
        self.snapshots = []

    def update(self, ref, updates):
        self.updates = updates

    def set(self, ref, entry):
        self.snapshots.append(entry)

    def delete(self, ref):
        pass


def _game(**overrides):
    game = copy.deepcopy(GAME)
    game.update(overrides)
    return _Ref(to_firestore_coords(game))


def test_a_hero_move_records_the_squares_walked():
    txn = _Txn()
    main._apply_movement.to_wrap(txn, _DB(), _game(), "barbarian", [[6, 2], [7, 2], [8, 2]])
    # Stored in Firestore's {x,y} shape like every other coordinate.
    assert from_firestore_coords(txn.updates["lastMoves"]) == {"barbarian": [[6, 2], [7, 2], [8, 2]]}


def test_a_move_cut_short_records_only_what_was_walked():
    # (7,3) is a hidden pit: the hero drops in there and never reaches (7,4).
    txn = _Txn()
    main._apply_movement.to_wrap(txn, _DB(), _game(), "barbarian", [[6, 2], [7, 2], [7, 3], [7, 4]])
    path = from_firestore_coords(txn.updates["lastMoves"])["barbarian"]
    assert path[-1] == [7, 3]
    assert path == [[6, 2], [7, 2], [7, 3]]


def test_a_cleared_jump_hops_onto_and_past_the_trap():
    # The pit at (7,3) sits on R2's south wall, so the hero (north of
    # it) comes down on its west side -- the rulebook allows any open
    # side, and straight across would be through the wall.
    game = _game(
        heroes=[{"id": "barbarian", "name": "Barbarian", "pos": [7, 2], "active": True}],
        trapsFound={"R2-T1": {"type": "pit", "pos": [7, 3]}},
    )
    txn = _Txn()
    main._apply_trap_action.to_wrap(txn, _DB(), game, "barbarian", "R2-T1", "jump", "white_shield", (6, 3), False)
    assert from_firestore_coords(txn.updates["lastMoves"]) == {"barbarian": [[7, 2], [7, 3], [6, 3]]}


def test_a_failed_jump_ends_in_the_pit():
    game = _game(
        heroes=[{"id": "barbarian", "name": "Barbarian", "pos": [7, 2], "active": True}],
        trapsFound={"R2-T1": {"type": "pit", "pos": [7, 3]}},
    )
    txn = _Txn()
    main._apply_trap_action.to_wrap(txn, _DB(), game, "barbarian", "R2-T1", "jump", "skull", (6, 3), False)
    assert from_firestore_coords(txn.updates["lastMoves"]) == {"barbarian": [[7, 2], [7, 3]]}


def test_a_disarm_moves_nobody():
    game = _game(
        heroes=[{"id": "dwarf", "name": "Dwarf", "pos": [7, 2], "active": True}],
        trapsFound={"R2-T1": {"type": "pit", "pos": [7, 3]}},
    )
    txn = _Txn()
    main._apply_trap_action.to_wrap(txn, _DB(), game, "dwarf", "R2-T1", "disarm", "skull", None, False)
    assert txn.updates["lastMoves"] == {}


def test_zargons_turn_records_each_monsters_walk():
    txn = _Txn()
    main._apply_zargon_turn.to_wrap(txn, _DB(), _game(phase="zargon"), "normal", None)
    moves = from_firestore_coords(txn.updates["lastMoves"])
    path = moves["M1"]
    assert path[0] == [8, 3]
    assert path[-1] == from_firestore_coords(txn.updates["monsters.M1.pos"])
    assert all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1 for a, b in zip(path, path[1:]))


def test_zargons_turn_writes_the_field_whole_so_a_hero_path_cannot_linger():
    # Nothing to move: the one monster is dead. The hero's path from the
    # phase before must not survive into Zargon's write.
    game = _game(phase="zargon", monsters={"M1": {"pos": [8, 3], "currentBody": 0, "alive": False}})
    game._data["lastMoves"] = to_firestore_coords({"barbarian": [[5, 2], [6, 2]]})
    txn = _Txn()
    main._apply_zargon_turn.to_wrap(txn, _DB(), game, "normal", None)
    assert txn.updates["lastMoves"] == {}
