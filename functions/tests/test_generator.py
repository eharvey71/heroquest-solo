"""Generator pipeline tests. Never call the real Anthropic API — a fake
client with a `.messages.create` matching the SDK's response shape drives
every case, so these run offline and deterministically.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from generator.client import QuestGenerationRefused
from generator.core import QuestGenerationFailed, generate_quest
from generator.repair import _total_budget


@pytest.fixture(autouse=True)
def pin_stairway_room(monkeypatch):
    """generate_quest now pre-picks a random stairway room and enforces
    it (see generator/prompt.py's pick_stairway_room) -- these tests are
    about the retry/repair/truncation pipeline, not room selection, and
    every fixture quest here declares stairway.room "R1". Pin the pick
    so a random room doesn't fail these fixtures' own validation.
    """
    monkeypatch.setattr("generator.core.pick_stairway_room", lambda catalogs, rng=None: "R1")


def _to_wire_format(quest: dict) -> dict:
    """Inverse of generator.client._to_canonical_shape: fixtures are
    written in the canonical {roomId: room} dict shape, but the real API
    (and this fake) speaks the array-with-roomId wire format (see
    generator/schema.py's module docstring for why). Converting here
    means these tests exercise the same conversion real responses go
    through, instead of bypassing it.
    """
    quest = copy.deepcopy(quest)
    quest["rooms"] = [{"roomId": rid, **room} for rid, room in quest["rooms"].items()]
    return quest


def _text_response(payload, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        content=[SimpleNamespace(type="text", text=json.dumps(_to_wire_format(payload)))],
    )


class ScriptedClient:
    """Replays a fixed sequence of quest payloads, one per call. Records
    every request's messages so tests can assert on retry-message content.
    """

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self._payloads[len(self.calls) - 1]
        return _text_response(payload)


class RefusingClient:
    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            stop_reason="refusal",
            stop_details=SimpleNamespace(category="cyber", explanation="nope"),
            content=[],
        )


def test_first_attempt_success(good_quest_4h, good_quest_4h_params, catalogs):
    client = ScriptedClient([good_quest_4h])
    result = generate_quest(good_quest_4h_params, client, catalogs)
    assert result.attempts == 1
    assert result.validation.ok
    assert len(client.calls) == 1


def test_retry_carries_forward_errors_and_succeeds(good_quest_4h, good_quest_4h_params, catalogs):
    bad = copy.deepcopy(good_quest_4h)
    # sabotage something the schema can't catch: push the objective out of MIN_DEPTH range
    bad["objective"]["target"]["monsterId"] = "M13"  # R4, only 4 doors deep (needs 5)

    client = ScriptedClient([bad, good_quest_4h])
    result = generate_quest(good_quest_4h_params, client, catalogs)

    assert result.attempts == 2
    assert result.validation.ok
    # the second call's user message must be the retry message, quoting the real error
    second_call_message = client.calls[1]["messages"][0]["content"]
    assert "door(s) from the stairway" in second_call_message


def test_exhausts_after_three_attempts_and_raises(good_quest_4h, good_quest_4h_params, catalogs):
    bad = copy.deepcopy(good_quest_4h)
    bad["rooms"]["R2"]["monsters"][0]["type"] = "beholder"  # not in the schema enum... but the
    # fake client bypasses schema enforcement (only the real API enforces output_config.format),
    # so this still reaches the validator and fails there every time.

    client = ScriptedClient([bad, bad, bad])
    with pytest.raises(QuestGenerationFailed) as exc_info:
        generate_quest(good_quest_4h_params, client, catalogs)

    assert exc_info.value.attempts == 3
    assert len(client.calls) == 3
    assert any("beholder" in e for e in exc_info.value.errors)


def test_auto_repair_absorbs_trivial_issue_within_one_attempt(good_quest_4h, good_quest_4h_params, catalogs):
    low_budget = copy.deepcopy(good_quest_4h)
    low_budget["rooms"]["R4"]["monsters"] = low_budget["rooms"]["R4"]["monsters"][:1]
    assert _total_budget(low_budget, catalogs) < 108  # below the 4h standard floor

    client = ScriptedClient([low_budget])
    result = generate_quest(good_quest_4h_params, client, catalogs)

    # repaired silently before validation ever ran -- no retry needed
    assert result.attempts == 1
    assert len(client.calls) == 1
    assert result.validation.ok


def test_refusal_propagates_without_retrying(good_quest_4h_params, catalogs):
    client = RefusingClient()
    with pytest.raises(QuestGenerationRefused):
        generate_quest(good_quest_4h_params, client, catalogs)
    assert client.calls == 1  # a refusal isn't a validation failure -- retrying identically won't help


class TruncatingThenGoodClient:
    """First call: stop_reason=max_tokens with an incomplete JSON body
    (what a real truncated structured-output response looks like).
    Second call: a good quest.
    """

    def __init__(self, good_payload):
        self._good_payload = good_payload
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                stop_reason="max_tokens",
                stop_details=None,
                content=[SimpleNamespace(type="text", text='{"id": "abc", "title": "Cut')],
            )
        return _text_response(self._good_payload)


def test_truncated_response_retries_instead_of_crashing(good_quest_4h, good_quest_4h_params, catalogs):
    client = TruncatingThenGoodClient(good_quest_4h)
    result = generate_quest(good_quest_4h_params, client, catalogs)

    assert result.attempts == 2
    assert result.validation.ok
    assert len(client.calls) == 2
    # the retry message should explain the truncation, not leak a raw JSONDecodeError
    retry_message = client.calls[1]["messages"][0]["content"]
    assert "cut off" in retry_message


def test_pipeline_fences_the_play_area_before_returning(good_quest_4h, good_quest_4h_params, catalogs):
    # The model is told to declare no blockedSquares; the cordon is the
    # pipeline's own last step (generator/fence.py).
    good_quest_4h["blockedSquares"] = []
    client = ScriptedClient([good_quest_4h])
    result = generate_quest(good_quest_4h_params, client, catalogs)

    fence = [tuple(sq) for sq in result.quest["blockedSquares"]]
    assert fence
    assert all(catalogs.board.area_of[sq] == "CORRIDOR" for sq in fence)
    assert result.validation.ok


# ---- prompt-embedded schema + tolerant parsing (no structured outputs;
# see generator/client.py's module docstring for why) ----

from generator.client import QuestGenerationMalformed, extract_json  # noqa: E402
from generator.core import MALFORMED_RETRY_HINT  # noqa: E402


def test_request_embeds_schema_in_system_prompt_not_output_config(good_quest_4h, good_quest_4h_params, catalogs):
    client = ScriptedClient([good_quest_4h])
    generate_quest(good_quest_4h_params, client, catalogs)
    kwargs = client.calls[0]
    assert "format" not in kwargs.get("output_config", {})
    assert '"$defs"' in kwargs["system"]
    assert "OUTPUT FORMAT" in kwargs["system"]


def test_extract_json_strips_markdown_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_tolerates_prose_around_the_object():
    assert extract_json('Here is the quest:\n{"a": {"b": 2}}\nDone!') == {"a": {"b": 2}}


def test_extract_json_raises_malformed_when_no_object():
    with pytest.raises(QuestGenerationMalformed):
        extract_json("I could not produce a quest.")


class MalformedThenGoodClient:
    """First call: a complete (not truncated) response that isn't JSON.
    Second call: a valid quest. The loop must retry with the emit-JSON
    hint rather than crashing or using the truncation hint."""

    def __init__(self, good_payload):
        self._good_payload = good_payload
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return SimpleNamespace(
                stop_reason="end_turn",
                stop_details=None,
                content=[SimpleNamespace(type="text", text="Sorry, here is a description instead.")],
            )
        return _text_response(self._good_payload)


def test_malformed_response_retries_with_json_hint(good_quest_4h, good_quest_4h_params, catalogs):
    client = MalformedThenGoodClient(good_quest_4h)
    result = generate_quest(good_quest_4h_params, client, catalogs)
    assert result.attempts == 2
    retry_text = client.calls[1]["messages"][0]["content"]
    assert MALFORMED_RETRY_HINT in retry_text
