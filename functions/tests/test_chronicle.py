"""Chronicle generation tests. Never call the real Anthropic API -- a
fake client with a `.messages.create` matching the SDK's response shape
drives every case, same convention as tests/test_generator.py.
"""

from types import SimpleNamespace

import pytest

from generator.chronicle import (
    ChronicleRefused,
    ChronicleTruncated,
    build_chronicle_prompt,
    call_chronicle_llm,
)

QUEST = {
    "title": "The Tomb of the Ashen King",
    "backstory": "An old evil stirs beneath the crypt.",
    "objective": {"description": "Slay the Ashen King."},
    "completionText": "The Ashen King crumbles to dust. You have recovered the Wand of Magic.",
}

GAME = {
    "status": "complete",
    "heroes": [
        {"id": "barbarian", "name": "Barbarian", "alive": True},
        {"id": "wizard", "name": "Wizard", "alive": False},
    ],
    "log": [
        {"turn": 1, "text": "The party begins their quest."},
        {"turn": 3, "text": "orc attacks Wizard: 3 dice, 3 skull(s)."},
        {"turn": 3, "text": "Wizard has fallen."},
        {"turn": 8, "text": "The Ashen King is defeated!"},
    ],
}


def _text_response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        content=[SimpleNamespace(type="text", text=text)],
    )


class ScriptedClient:
    def __init__(self, response):
        self._response = response
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_prompt_includes_quest_and_log_and_roster():
    prompt = build_chronicle_prompt(QUEST, GAME)
    assert "The Tomb of the Ashen King" in prompt
    assert "Wand of Magic" in prompt
    assert "Wizard: fell in battle" in prompt
    assert "Barbarian: survived" in prompt
    assert "The Ashen King is defeated!" in prompt
    assert "OUTCOME: victory" in prompt


def test_lost_game_reports_defeat_outcome():
    lost_game = {**GAME, "status": "lost"}
    prompt = build_chronicle_prompt(QUEST, lost_game)
    assert "OUTCOME: defeat" in prompt


def test_call_returns_stripped_text():
    client = ScriptedClient(_text_response("  A tale of woe.  "))
    result = call_chronicle_llm(client, QUEST, GAME)
    assert result == "A tale of woe."
    assert client.calls[0]["messages"][0]["content"] == build_chronicle_prompt(QUEST, GAME)


def test_refusal_raises():
    client = ScriptedClient(_text_response("", stop_reason="refusal"))
    with pytest.raises(ChronicleRefused):
        call_chronicle_llm(client, QUEST, GAME)


def test_truncation_raises():
    client = ScriptedClient(_text_response("cut off mid-sen", stop_reason="max_tokens"))
    with pytest.raises(ChronicleTruncated):
        call_chronicle_llm(client, QUEST, GAME)


def test_empty_text_is_treated_as_a_refusal():
    client = ScriptedClient(SimpleNamespace(stop_reason="end_turn", stop_details=None, content=[]))
    with pytest.raises(ChronicleRefused):
        call_chronicle_llm(client, QUEST, GAME)


class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data) if self._data else None


class _Ref:
    def __init__(self, data):
        self._data = data
        self.updated_with = None

    def get(self, transaction=None):
        return _Snap(self._data)

    def update(self, updates):
        self.updated_with = updates
        self._data = {**(self._data or {}), **updates}

    def collection(self, name):
        return _Coll({})


class _Coll:
    def __init__(self, docs):
        self._docs = docs

    def document(self, name):
        return _Ref(self._docs.get(name))


class _DB:
    def __init__(self, quest_id, quest):
        self._quest_id = quest_id
        self._quest = quest

    def collection(self, name):
        return _Coll({self._quest_id: self._quest})


def test_endpoint_writes_the_chronicle_onto_a_finished_game():
    from main import _apply_generate_chronicle

    game_ref = _Ref({**GAME, "questId": "Q1"})
    db = _DB("Q1", QUEST)
    client = ScriptedClient(_text_response("They triumphed."))

    result = _apply_generate_chronicle(db, game_ref, client)
    assert result == "They triumphed."
    assert game_ref.updated_with == {"chronicle": "They triumphed."}


def test_endpoint_refuses_an_in_progress_game():
    import main

    game_ref = _Ref({**GAME, "questId": "Q1", "status": "in_progress"})
    db = _DB("Q1", QUEST)
    client = ScriptedClient(_text_response("too soon"))

    with pytest.raises(main.https_fn.HttpsError) as exc_info:
        main._apply_generate_chronicle(db, game_ref, client)
    assert exc_info.value.code == main.https_fn.FunctionsErrorCode.FAILED_PRECONDITION
    assert "still in progress" in exc_info.value.message
    # Never reached the LLM, and never wrote anything.
    assert client.calls == []
    assert game_ref.updated_with is None


def test_system_prompt_forbids_raw_room_and_square_ids():
    from generator.chronicle import SYSTEM_PROMPT

    assert "room ids" in SYSTEM_PROMPT
    assert "NEVER print" in SYSTEM_PROMPT
