"""main._purge: the owner's backend clean-up, against a fake client."""

import pytest
from firebase_functions import https_fn

import main


class _Ref:
    def __init__(self, coll, doc_id):
        self.coll, self.id = coll, doc_id


class _Snap:
    def __init__(self, coll, doc_id, data):
        self.reference, self.id, self._data = _Ref(coll, doc_id), doc_id, data

    def to_dict(self):
        return self._data


class _FakeDB:
    def __init__(self, data):
        self.data = {name: dict(docs) for name, docs in data.items()}
        self.deleted = []

    def collection(self, name):
        db = self

        class _Coll:
            def stream(self):
                return [_Snap(name, i, d) for i, d in list(db.data.get(name, {}).items())]

        return _Coll()

    def recursive_delete(self, ref):
        self.deleted.append((ref.coll, ref.id))
        del self.data[ref.coll][ref.id]


def _db():
    return _FakeDB({
        "quests": {"QA": {"archived": True}, "QB": {"archived": True}, "QC": {}},
        "games": {
            "G1": {"questId": "QA", "archived": True},
            "G2": {"questId": "QB"},  # live game on a removed quest keeps the quest
            "G3": {"questId": "QC"},
        },
        "generationJobs": {"J1": {"stage": "done"}},
    })


def test_removed_scope_deletes_only_what_was_removed_and_keeps_a_quest_still_played():
    db = _db()
    counts = main._purge(db, "removed")
    assert counts == {"quests": 1, "games": 1, "jobs": 1}
    assert set(db.data["quests"]) == {"QB", "QC"}
    assert set(db.data["games"]) == {"G2", "G3"}
    assert db.data["generationJobs"] == {}


def test_everything_scope_wipes_all_three_collections():
    db = _db()
    counts = main._purge(db, "everything")
    assert counts == {"quests": 3, "games": 3, "jobs": 1}
    assert all(not docs for docs in db.data.values())


def test_an_unknown_scope_is_refused():
    with pytest.raises(https_fn.HttpsError):
        main._purge(_db(), "some")
