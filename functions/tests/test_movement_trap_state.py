"""A trap sprung by walking must leave its position in game state.

trapsTriggered alone is just ids -- without a {trapId: {type,pos}}
entry in trapsFound the client had no square to draw, so a sprung pit
vanished from the app while its tile sat on the physical board. Fake
Firestore, same conventions as test_main_defence_queue.py.
"""

import copy

import main
from firestore_coords import to_firestore_coords

QUEST = {
    "doors": [{"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"}],
    "objective": {"type": "kill_boss", "description": "x", "target": {"room": "R2"}},
    "wanderingMonster": "orc",
    "rooms": {"R2": {"monsters": [], "traps": [{"type": "pit", "pos": [7, 3]}], "furniture": []}},
    "stairway": {"room": "R1", "pos": [1, 1]},
}

GAME = {
    "questId": "Q1",
    "phase": "hero",
    "status": "in_progress",
    "turn": 3,
    "heroes": [{"id": "barbarian", "name": "Barbarian", "pos": [7, 2], "active": True}],
    "monsters": {},
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


def test_a_pit_sprung_by_walking_keeps_its_position_in_traps_found():
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(copy.deepcopy(GAME)))
    main._apply_movement.to_wrap(txn, _DB(), game_ref, "barbarian", [[7, 2], [7, 3]])

    assert "R2-T1" in txn.updates["trapsTriggered"]
    found = txn.updates["trapsFound"]
    assert found["R2-T1"]["type"] == "pit"
    # Coordinates go to Firestore in {x,y} shape like every other pos.
    assert found["R2-T1"]["pos"] == {"x": 7, "y": 3}
