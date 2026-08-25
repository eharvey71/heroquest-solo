"""The two-step treasure flow: search first, report the drawn card
second (main.resolve_treasure_draw). Fake Firestore, same conventions
as test_main_defence_queue.py.

The old flow asked "wandering monster drawn?" as a checkbox BEFORE the
search -- but the player can only know after the app has ruled the
search legal and un-trapped and they have physically drawn. These
tests pin the new order and the legacy single-call path side by side.
"""

import copy

import pytest

import main
from engine.end_turn import TreasureDrawPendingError, resolve_end_turn
from firestore_coords import to_firestore_coords

QUEST = {
    "doors": [{"id": "D1", "squares": [[4, 1], [5, 1]], "state": "open"}],
    "objective": {"type": "kill_boss", "description": "x", "target": {"room": "R2"}},
    "wanderingMonster": "orc",
    "rooms": {"R2": {"monsters": [], "traps": [], "furniture": []}},
    "stairway": {"room": "R1", "pos": [1, 1]},
}

GAME = {
    "questId": "Q1",
    "phase": "hero",
    "status": "in_progress",
    "turn": 7,
    "heroes": [{"id": "barbarian", "name": "Barbarian", "pos": [7, 2], "active": True}],
    "monsters": {},
    "revealed": {"rooms": ["R1", "R2"], "corridorSquares": []},
    "doors": {"D1": "open"},
    "searched": {},
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

    def delete(self, ref):
        pass


def _search(game=None, wandering=None):
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(copy.deepcopy(game or GAME)))
    main._apply_search_treasure.to_wrap(txn, _DB(QUEST), game_ref, "barbarian", "R2", wandering)
    return txn


def _resolve_draw(game, wandering):
    txn = _Txn()
    game_ref = _Ref(to_firestore_coords(copy.deepcopy(game)))
    main._apply_resolve_treasure_draw.to_wrap(txn, _DB(QUEST), game_ref, wandering)
    return txn


PENDING_GAME = {**GAME, "pendingTreasureDraw": {"heroId": "barbarian", "roomId": "R2"}}


def test_flagless_search_owes_a_card_report():
    txn = _search()
    assert txn.updates["pendingTreasureDraw"] == {"heroId": "barbarian", "roomId": "R2"}
    assert any("Draw ONE treasure card" in e["text"] for e in txn.updates["log"])
    # The search itself is spent now, not when the card is reported.
    assert "searched.R2.treasureBy" in txn.updates


def test_legacy_explicit_false_resolves_in_one_call():
    txn = _search(wandering=False)
    assert "pendingTreasureDraw" not in txn.updates
    assert not any(k.startswith("monsters.") for k in txn.updates)


def test_legacy_explicit_true_spawns_in_one_call():
    txn = _search(wandering=True)
    assert "pendingTreasureDraw" not in txn.updates
    assert any(k.startswith("monsters.") for k in txn.updates)
    assert txn.updates["pendingDefenses"]


def test_hero_actions_are_blocked_while_the_card_is_unreported():
    with pytest.raises(main.https_fn.HttpsError) as exc_info:
        main._require_no_pending_defenses(PENDING_GAME)
    assert "wandering monster" in exc_info.value.message


def test_end_turn_is_blocked_while_the_card_is_unreported():
    with pytest.raises(TreasureDrawPendingError):
        resolve_end_turn(PENDING_GAME)


def test_reporting_no_monster_just_clears_the_pending_state():
    txn = _resolve_draw(PENDING_GAME, wandering=False)
    assert txn.updates["pendingTreasureDraw"] is None
    assert not any(k.startswith("monsters.") for k in txn.updates)
    assert any("No wandering monster" in e["text"] for e in txn.updates["log"])
    # An undo snapshot exists: reporting the card is a real action.
    assert txn.snapshots


def test_reporting_the_monster_spawns_it_and_queues_its_attack():
    txn = _resolve_draw(PENDING_GAME, wandering=True)
    assert txn.updates["pendingTreasureDraw"] is None
    monster_keys = [k for k in txn.updates if k.startswith("monsters.")]
    assert len(monster_keys) == 1
    spawned = txn.updates[monster_keys[0]]
    assert spawned["type"] == "orc"
    pending = txn.updates["pendingDefenses"]
    assert len(pending) == 1
    assert pending[0]["heroId"] == "barbarian"
    assert pending[0]["monsterName"] == "orc"
    assert any("place" in i.lower() for i in txn.updates["placementInstructions"])


def test_reporting_with_nothing_pending_is_refused():
    with pytest.raises(main.https_fn.HttpsError) as exc_info:
        _resolve_draw(GAME, wandering=False)
    assert "no treasure card" in exc_info.value.message
