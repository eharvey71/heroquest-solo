"""generator/side_quests.py: the second model call, driven by a fake
client. Never touches the real API."""

import copy
import json
import random
from types import SimpleNamespace

import pytest

from generator.prompt import build_system_prompt
from generator.side_quests import (
    SideQuestGenerationFailed,
    build_gate_spec,
    build_side_quest_system_prompt,
    generate_side_quests,
    roll_required,
)
from generator.side_quest_schema import build_side_quest_json_schema, to_canonical_side_quests
from tests.test_side_quests_validator import _scene


def _wire(sq: dict) -> dict:
    """Canonical -> the array-with-id wire format the model emits."""
    sq = copy.deepcopy(sq)
    passages = []
    for pid, p in sq["passages"].items():
        for c in p["choices"]:
            c.setdefault("requiresHero", "")
            c.setdefault("requiresElement", "")
            c.setdefault("requiresFlag", "")
            c.setdefault("setsFlag", "")
            c.setdefault("next", "")
            c.setdefault("test", {"kind": "none", "dice": 0, "needSkulls": 0, "success": "", "failure": ""})
        passages.append({"id": pid, **p})
    terminals = [{"id": tid, **t} for tid, t in sq["terminals"].items()]
    sq["passages"], sq["terminals"] = passages, terminals
    sq["retry"] = sq.get("retry") or {"from": "", "to": "", "costText": ""}
    return sq


def _response(payload, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
    )


class ScriptedClient:
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self._payloads.pop(0)
        return payload if isinstance(payload, SimpleNamespace) else _response(payload)


PARAMS = {"heroCount": 4, "difficulty": "standard", "size": "full", "mode": "expanded"}


def test_wire_shape_round_trips_to_canonical():
    canonical = _scene()
    assert to_canonical_side_quests({"sideQuests": [_wire(canonical)]})[0]["passages"].keys() == canonical["passages"].keys()
    out = to_canonical_side_quests({"sideQuests": [_wire(canonical)]})[0]
    assert out["retry"] is None
    assert out["passages"]["p1"]["choices"][0]["test"] is None
    assert out["passages"]["p2"]["choices"][0]["test"]["kind"] == "combat_dice"


def test_a_valid_first_answer_is_accepted(good_quest_4h, catalogs):
    client = ScriptedClient([{"sideQuests": [_wire(_scene())]}])
    result = generate_side_quests(good_quest_4h, PARAMS, client, catalogs, gate=None)
    assert result.attempts == 1
    assert [sq["id"] for sq in result.side_quests] == ["SQ1"]
    # The schema rides in the system prompt, as the quest's does.
    system = client.calls[0]["system"]
    assert "OUTPUT FORMAT" in system and '"sideQuests"' in system


def test_validator_errors_come_back_as_the_retry_message(good_quest_4h, catalogs):
    bad = _scene()
    bad["passages"]["p1"]["choices"][0]["next"] = "nowhere"
    client = ScriptedClient([{"sideQuests": [_wire(bad)]}, {"sideQuests": [_wire(_scene())]}])
    result = generate_side_quests(good_quest_4h, PARAMS, client, catalogs, gate=None)
    assert result.attempts == 2
    retry = client.calls[1]["messages"][0]["content"]
    assert "failed validation" in retry and "nowhere" in retry


def test_three_bad_answers_raise(good_quest_4h, catalogs):
    bad = _scene()
    bad["passages"]["p1"]["text"] = "Go to R12."
    client = ScriptedClient([{"sideQuests": [_wire(bad)]}] * 3)
    with pytest.raises(SideQuestGenerationFailed) as exc_info:
        generate_side_quests(good_quest_4h, PARAMS, client, catalogs, gate=None)
    assert exc_info.value.attempts == 3
    assert any("room id" in e for e in exc_info.value.errors)


def test_a_truncated_answer_asks_for_shorter_scenes(good_quest_4h, catalogs):
    client = ScriptedClient([_response({}, stop_reason="max_tokens"), {"sideQuests": [_wire(_scene())]}])
    # An empty object is malformed for our purposes only once parsed;
    # the fake returns "{}" so make the first reply genuinely cut off.
    client._payloads[0] = SimpleNamespace(stop_reason="max_tokens", stop_details=None, content=[SimpleNamespace(type="text", text='{"sideQuests": [')])
    result = generate_side_quests(good_quest_4h, PARAMS, client, catalogs, gate=None)
    assert result.attempts == 2
    assert "shorter" in client.calls[1]["messages"][0]["content"]


def test_gate_spec_follows_the_objective(good_quest_4h):
    spec = build_gate_spec(good_quest_4h)
    assert spec == {"kind": "ward", "targetMonsterId": "M17", "targetName": "Vorlag the Cruel"}
    quest = copy.deepcopy(good_quest_4h)
    quest["objective"] = {"type": "rescue", "description": "x", "target": {"room": "R12"}}
    assert build_gate_spec(quest) == {"kind": "seal", "targetRoom": "R12"}


def test_the_required_coin_is_roughly_one_in_three():
    rng = random.Random(7)
    hits = sum(roll_required(rng) for _ in range(3000))
    assert 850 < hits < 1150


def test_the_prompt_names_the_gate_and_the_armory_rule(catalogs):
    prompt = build_side_quest_system_prompt(catalogs, {"kind": "ward", "targetMonsterId": "M17", "targetName": "Vorlag"})
    assert "Vorlag" in prompt and "break_gate" in prompt
    assert "ONLY a town scene mentions the Armory" in prompt
    assert "Ring of Return" in prompt
    prompt = build_side_quest_system_prompt(catalogs, None)
    assert "NO REQUIRED SIDE QUEST" in prompt


def test_the_main_quest_prompt_plants_the_ward_only_when_asked(catalogs):
    with_gate = build_system_prompt({**PARAMS, "requiredSideQuest": True}, catalogs, "R1")
    without = build_system_prompt(PARAMS, catalogs, "R1")
    assert "REQUIRED SIDE QUEST WILL GATE" in with_gate
    assert "REQUIRED SIDE QUEST" not in without


def test_the_schema_enumerates_this_quests_rooms_and_monsters(good_quest_4h, catalogs):
    schema = build_side_quest_json_schema(catalogs, good_quest_4h)
    text = json.dumps(schema)
    assert '"M17"' in text and '"R12"' in text and '"ring_of_return"' in text
