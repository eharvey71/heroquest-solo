"""main._resolve_campaign_context and _parse_generation_params's
continuesFromGameId handling. Fake Firestore, same convention as
test_chronicle.py and test_main_defence_queue.py.
"""

import pytest

import main

QUEST = {"title": "The Tomb of the Ashen King"}


class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data else None


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
    def __init__(self, game, quest_id="Q1", quest=QUEST):
        self._docs = {"games": {"G1": game}, "quests": {quest_id: quest}}

    def collection(self, name):
        return _Coll(self._docs.get(name, {}))


def test_a_finished_chronicled_game_resolves_to_campaign_context():
    game = {"questId": "Q1", "status": "complete", "chronicle": "They triumphed."}
    context = main._resolve_campaign_context(_DB(game), "G1")
    assert context == {"previousTitle": "The Tomb of the Ashen King", "chronicle": "They triumphed."}


def test_a_lost_game_also_qualifies():
    # Defeat is still a chronicle -- a campaign can continue from a loss.
    game = {"questId": "Q1", "status": "lost", "chronicle": "They fell."}
    context = main._resolve_campaign_context(_DB(game), "G1")
    assert context["chronicle"] == "They fell."


def test_an_in_progress_game_is_rejected():
    game = {"questId": "Q1", "status": "in_progress", "chronicle": None}
    with pytest.raises(main.https_fn.HttpsError) as exc_info:
        main._resolve_campaign_context(_DB(game), "G1")
    assert "still in progress" in exc_info.value.message


def test_a_finished_game_with_no_chronicle_yet_is_rejected():
    game = {"questId": "Q1", "status": "complete"}
    with pytest.raises(main.https_fn.HttpsError) as exc_info:
        main._resolve_campaign_context(_DB(game), "G1")
    assert "no chronicle yet" in exc_info.value.message


def test_parse_generation_params_carries_continues_from_game_id():
    params = main._parse_generation_params({"heroCount": 4, "continuesFromGameId": "G1"})
    assert params["continuesFromGameId"] == "G1"


def test_parse_generation_params_omits_it_when_absent():
    params = main._parse_generation_params({"heroCount": 4})
    assert "continuesFromGameId" not in params


def test_parse_generation_params_rejects_a_non_string_id():
    with pytest.raises(main.https_fn.HttpsError):
        main._parse_generation_params({"heroCount": 4, "continuesFromGameId": 123})
