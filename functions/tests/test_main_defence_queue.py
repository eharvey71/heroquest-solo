"""Fake-Firestore tests for the pendingDefenses queue in main.py.

main.py's _apply_* functions had no coverage at all -- they need a
transaction and a document reference, so nothing exercised them and a
write that only fails against real Firestore reached production. These
fakes are the minimum that lets the apply functions run: a document
snapshot, a collection lookup, and a transaction that records what it
was asked to write.
"""

import copy

import pytest

import main
from firestore_coords import to_firestore_coords

QUEST = {
    "doors": [{"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"}],
    "objective": {"type": "kill_boss", "description": "x", "target": {"room": "R2"}},
    "wanderingMonster": "orc",
    "rooms": {
        "R2": {
            "monsters": [{"id": "M1", "type": "chaos_warrior", "name": "Vorlag", "pos": [8, 3]}],
            "traps": [],
            "furniture": [],
        }
    },
    "stairway": {"room": "R1", "pos": [1, 1]},
}

GAME = {
    "questId": "Q1",
    "phase": "zargon",
    "status": "in_progress",
    "turn": 7,
    "heroes": [{"id": "barbarian", "name": "Barbarian", "pos": [7, 2], "active": True}],
    "monsters": {"M1": {"pos": [7, 3], "currentBody": 3, "alive": True}},
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
    def __init__(self, quest):
        self._quest = quest

    def collection(self, name):
        return _Coll({"Q1": to_firestore_coords(copy.deepcopy(self._quest))})


class _Txn:
    def __init__(self):
        self.updates = None
        self.snapshots = []

    def update(self, ref, updates):
        self.updates = updates

    def set(self, ref, entry):
        self.snapshots.append(entry)


def _run_zargon_turn(turn_type, game=None, quest=None, lowest_bp="barbarian"):
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(copy.deepcopy(game or GAME)))
    main._apply_zargon_turn.to_wrap(txn, _DB(quest or QUEST), game_ref, turn_type, lowest_bp)
    return txn


@pytest.mark.parametrize("turn_type", ["normal", "cunning", "wandering"])
def test_every_turn_type_writes_a_defence_queue(turn_type):
    txn = _run_zargon_turn(turn_type)
    pending = txn.updates["pendingDefenses"]
    assert isinstance(pending, list)
    for entry in pending:
        assert set(entry) == {"id", "heroId", "heroName", "skulls", "monsterId", "monsterName", "pos"}
        assert entry["heroId"] == "barbarian"
        assert entry["skulls"] >= 0
        # The prompt has to say WHAT swung and where it stands, or the
        # player is told "3 skulls" with no figure to look for. monsterId
        # is what lets the client highlight the attacker's own token.
        assert entry["monsterId"]
        assert entry["monsterName"]
        assert len(entry["pos"]) == 2


def test_an_adjacent_monster_queues_its_attack():
    # M1 starts orthogonally adjacent to the hero, so a normal turn
    # always produces exactly one prompt.
    txn = _run_zargon_turn("normal")
    assert len(txn.updates["pendingDefenses"]) == 1
    assert txn.updates["pendingDefenses"][0]["id"] == "7:M1"


def test_the_queue_is_written_whole_so_stale_prompts_cannot_leak():
    game = copy.deepcopy(GAME)
    game["pendingDefenses"] = [
        {"id": "6:M9", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 2}
    ]
    txn = _run_zargon_turn("normal", game=game)
    assert all(e["id"] != "6:M9" for e in txn.updates["pendingDefenses"])


def test_the_undo_snapshot_keeps_the_queue_it_replaced():
    game = copy.deepcopy(GAME)
    game["pendingDefenses"] = [
        {"id": "6:M9", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 2}
    ]
    txn = _run_zargon_turn("normal", game=game)
    assert txn.snapshots[0]["state"]["pendingDefenses"][0]["id"] == "6:M9"


def test_answering_a_prompt_removes_only_that_one():
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["pendingDefenses"] = [
        {"id": "7:M1", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 2},
        {"id": "7:M2", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 3},
    ]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    main._apply_record_hero_defense.to_wrap(txn, game_ref, "barbarian", 2, 1, "7:M1")
    assert [e["id"] for e in txn.updates["pendingDefenses"]] == ["7:M2"]


def test_a_client_that_sends_no_id_falls_back_to_first_match():
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["pendingDefenses"] = [
        {"id": "7:M1", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 2},
        {"id": "7:M2", "heroId": "barbarian", "heroName": "Barbarian", "skulls": 3},
    ]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    main._apply_record_hero_defense.to_wrap(txn, game_ref, "barbarian", 3, 1, None)
    assert [e["id"] for e in txn.updates["pendingDefenses"]] == ["7:M1"]


def test_a_wandering_monster_card_names_what_walked_in():
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["heroes"][0]["pos"] = [6, 2]
    game["monsters"] = {}
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    main._apply_search_treasure.to_wrap(txn, _DB(QUEST), game_ref, "barbarian", "R2", True)

    # The player has never seen this figure: the prompt must say what it
    # is and where to stand it, and a placement line must accompany it.
    prompt = txn.updates["pendingDefenses"][-1]
    assert prompt["monsterId"] == "W1"
    assert prompt["monsterName"] == "orc"
    assert prompt["pos"]
    assert any("orc" in line for line in txn.updates["placementInstructions"])


def test_ending_the_hero_phase_clears_stale_placements():
    game = copy.deepcopy(GAME)
    game["phase"] = "hero"
    game["placementInstructions"] = ["Place the orc mini at square [6,1]."]
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(game))
    main._apply_end_turn.to_wrap(txn, game_ref)
    assert txn.updates["placementInstructions"] == []
