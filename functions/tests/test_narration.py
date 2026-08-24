"""Turn narration tests. Never call the real Anthropic API -- a fake
client with a `.messages.create` matching the SDK's response shape
drives every case, same convention as test_chronicle.py.
"""

from types import SimpleNamespace

import pytest

from generator.narration import (
    NarrationRefused,
    NarrationTruncated,
    build_narration_prompt,
    call_turn_narration_llm,
)

QUEST = {
    "title": "The Tomb of the Ashen King",
    "backstory": "An old evil stirs beneath the crypt.",
}

LOG = [
    {"turn": 1, "text": "The party begins their quest."},
    {"turn": 3, "text": "orc attacks Wizard: 3 dice, 3 skull(s)."},
    {"turn": 3, "text": "Wizard has fallen."},
]

GAME = {"status": "in_progress", "log": LOG}


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


def test_prompt_includes_quest_and_only_that_turns_log_lines():
    prompt = build_narration_prompt(QUEST, 3, ["orc attacks Wizard: 3 dice, 3 skull(s).", "Wizard has fallen."])
    assert "The Tomb of the Ashen King" in prompt
    assert "TURN 3 LOG" in prompt
    assert "Wizard has fallen." in prompt


def test_call_returns_stripped_text():
    client = ScriptedClient(_text_response("  The orc's blade finds its mark.  "))
    result = call_turn_narration_llm(client, QUEST, 3, ["orc attacks Wizard."])
    assert result == "The orc's blade finds its mark."
    assert client.calls[0]["messages"][0]["content"] == build_narration_prompt(QUEST, 3, ["orc attacks Wizard."])


def test_refusal_raises():
    client = ScriptedClient(_text_response("", stop_reason="refusal"))
    with pytest.raises(NarrationRefused):
        call_turn_narration_llm(client, QUEST, 1, ["nothing happened"])


def test_truncation_raises():
    client = ScriptedClient(_text_response("cut off mid-sen", stop_reason="max_tokens"))
    with pytest.raises(NarrationTruncated):
        call_turn_narration_llm(client, QUEST, 1, ["nothing happened"])


def test_empty_text_is_treated_as_a_refusal():
    client = ScriptedClient(SimpleNamespace(stop_reason="end_turn", stop_details=None, content=[]))
    with pytest.raises(NarrationRefused):
        call_turn_narration_llm(client, QUEST, 1, ["nothing happened"])


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


def test_endpoint_writes_narration_keyed_by_turn():
    from main import _apply_generate_turn_narration

    game_ref = _Ref({**GAME, "questId": "Q1"})
    db = _DB("Q1", QUEST)
    client = ScriptedClient(_text_response("The orc's blade finds its mark."))

    result = _apply_generate_turn_narration(db, game_ref, client, 3)
    assert result == "The orc's blade finds its mark."
    assert game_ref.updated_with == {"narration.3": "The orc's blade finds its mark."}


def test_endpoint_is_idempotent_and_skips_the_llm_when_already_narrated():
    from main import _apply_generate_turn_narration

    game_ref = _Ref({**GAME, "questId": "Q1", "narration": {"3": "Already told."}})
    db = _DB("Q1", QUEST)
    client = ScriptedClient(_text_response("A different telling."))

    result = _apply_generate_turn_narration(db, game_ref, client, 3)
    assert result == "Already told."
    assert client.calls == []
    assert game_ref.updated_with is None


def test_endpoint_rejects_a_turn_with_no_log_entries_yet():
    import main

    game_ref = _Ref({**GAME, "questId": "Q1"})
    db = _DB("Q1", QUEST)
    client = ScriptedClient(_text_response("too soon"))

    with pytest.raises(main.https_fn.HttpsError) as exc_info:
        main._apply_generate_turn_narration(db, game_ref, client, 99)
    assert exc_info.value.code == main.https_fn.FunctionsErrorCode.FAILED_PRECONDITION
    assert "hasn't closed" in exc_info.value.message
    assert client.calls == []
    assert game_ref.updated_with is None
