"""Undo: a stack of full snapshots, popped one at a time.

The Firestore transaction lives in main.py; these test the part that
decides WHAT goes back on the board (engine/undo.py).
"""

import pytest

from engine.undo import NothingToUndoError, build_snapshot, restore, snapshot_id


def _game(turn=1, **extra):
    state = {
        "turn": turn,
        "status": "in_progress",
        "heroes": [{"id": "barbarian", "name": "Barbarian", "pos": [2, 2], "alive": True}],
        "monsters": {},
        "log": [{"turn": 1, "text": "The party begins their quest."}],
        "createdAt": "2026-01-01",
    }
    state.update(extra)
    return state


def test_snapshot_ids_sort_in_play_order():
    assert sorted([snapshot_id(2), snapshot_id(10), snapshot_id(1)]) == [
        snapshot_id(1), snapshot_id(2), snapshot_id(10)
    ]


def test_first_snapshot_starts_the_stack_at_one():
    depth, entry, updates = build_snapshot(_game(), "the hero's move")
    assert depth == 1
    assert updates == {"undoDepth": 1, "undoLabel": "the hero's move"}
    assert entry["prevLabel"] is None


def test_snapshot_leaves_out_the_bookkeeping():
    before = _game(undoDepth=3, undoLabel="the attack")
    depth, entry, _ = build_snapshot(before, "the spell")
    assert depth == 4
    assert entry["prevLabel"] == "the attack"
    for field in ("createdAt", "undoDepth", "undoLabel"):
        assert field not in entry["state"]


def test_restore_drops_whatever_the_action_added():
    # The point of snapshotting whole states: a searched room and a
    # spawned monster have to VANISH, which no field merge can express.
    before = _game()
    _, entry, updates = build_snapshot(before, "the treasure search")

    after = {
        **_game(),
        **updates,
        "searched": {"R2": {"treasureBy": ["barbarian"]}},
        "monsters": {"W1": {"type": "orc", "alive": True}},
    }

    restored = restore(after, entry)
    assert "searched" not in restored
    assert restored["monsters"] == {}
    assert restored["undoDepth"] == 0


def test_restore_keeps_the_documents_creation_time():
    before = _game()
    _, entry, updates = build_snapshot(before, "the attack")
    restored = restore({**before, **updates}, entry)
    assert restored["createdAt"] == "2026-01-01"


def test_restore_says_what_it_undid():
    before = _game()
    _, entry, updates = build_snapshot(before, "the hero's move")
    restored = restore({**before, **updates}, entry)
    assert "Undone: the hero's move" in restored["log"][-1]["text"]
    assert len(restored["log"]) == len(before["log"]) + 1


def test_undo_walks_back_down_the_stack():
    state = _game()
    entries = {}
    for label in ("the hero's move", "opening the door", "the attack"):
        depth, entry, updates = build_snapshot(state, label)
        entries[depth] = entry
        state = {**state, **updates, "turn": state["turn"] + 1}

    assert state["undoDepth"] == 3
    for expected_label in ("the attack", "opening the door", "the hero's move"):
        assert entries[state["undoDepth"]]["label"] == expected_label
        state = restore(state, entries[state["undoDepth"]])
    assert state["undoDepth"] == 0
    assert state["undoLabel"] is None


def test_nothing_left_to_undo_is_an_error():
    with pytest.raises(NothingToUndoError):
        restore(_game(), {"state": {}, "label": "the attack"})


def test_a_lost_quest_can_still_be_undone():
    # Reporting the last hero's death by mistake has to be recoverable.
    before = _game()
    _, entry, updates = build_snapshot(before, "Barbarian's death")
    after = {**before, **updates, "status": "lost"}
    restored = restore(after, entry)
    assert restored["status"] == "in_progress"
