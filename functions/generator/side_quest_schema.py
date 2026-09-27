"""JSON Schema for the side-quest generation call, embedded in the
system prompt the same way the quest schema is (generator/client.py's
SCHEMA_INSTRUCTION). Everything is required-with-a-sentinel ("" / 0 /
"none" mean absent), so parsing is uniform and the shape rules stay
where they belong -- validator/side_quests.py is the real gate.

Wire format: passages and terminals are ARRAYS carrying their own id,
converted to {id: node} dicts by generator/side_quests.py right after
parsing (the same trick quest rooms use). Nothing downstream sees the
array form.
"""

from __future__ import annotations

from engine.side_quests import (
    COST_KINDS,
    EFFECT_TYPES,
    ELEMENTS,
    HERO_IDS,
    HOOK_WHENS,
    KINDS,
    OUTCOMES,
    REWARD_KINDS,
    SETTINGS,
    TEST_KINDS,
)
from validator.catalogs import Catalogs


def build_side_quest_json_schema(catalogs: Catalogs, quest: dict) -> dict:
    room_ids = sorted(quest.get("rooms", {}).keys())
    monster_ids = sorted(
        m["id"] for room in quest.get("rooms", {}).values() for m in room.get("monsters", []) if m.get("id")
    )
    effect = {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": list(EFFECT_TYPES)},
            "monsterId": {"type": "string", "enum": ["", *monster_ids]},
            "stat": {"type": "string", "enum": ["", "body", "defend"]},
            "room": {"type": "string", "enum": ["", *room_ids]},
            "heroId": {"type": "string", "enum": ["", *HERO_IDS]},
            "artifactId": {"type": "string", "enum": ["", *sorted(catalogs.artifacts.keys())]},
            "kind": {"type": "string", "enum": ["", *REWARD_KINDS, *[k for k in COST_KINDS if k not in REWARD_KINDS]]},
            "text": {"type": "string"},
        },
        "required": ["type", "monsterId", "stat", "room", "heroId", "artifactId", "kind", "text"],
        "additionalProperties": False,
    }
    test = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["none", *TEST_KINDS]},
            "dice": {"type": "integer"},
            "needSkulls": {"type": "integer"},
            "success": {"type": "string"},
            "failure": {"type": "string"},
        },
        "required": ["kind", "dice", "needSkulls", "success", "failure"],
        "additionalProperties": False,
    }
    choice = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "label": {"type": "string"},
            "requiresHero": {"type": "string", "enum": ["", *HERO_IDS]},
            "requiresElement": {"type": "string", "enum": ["", *ELEMENTS]},
            "requiresFlag": {"type": "string"},
            "setsFlag": {"type": "string"},
            "next": {"type": "string"},
            "test": test,
        },
        "required": ["id", "label", "requiresHero", "requiresElement", "requiresFlag", "setsFlag", "next", "test"],
        "additionalProperties": False,
    }
    passage = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "text": {"type": "string"},
            "choices": {"type": "array", "items": choice},
        },
        "required": ["id", "text", "choices"],
        "additionalProperties": False,
    }
    terminal = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "outcome": {"type": "string", "enum": list(OUTCOMES)},
            "text": {"type": "string"},
            "effects": {"type": "array", "items": effect},
        },
        "required": ["id", "outcome", "text", "effects"],
        "additionalProperties": False,
    }
    side_quest = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "kind": {"type": "string", "enum": list(KINDS)},
            "title": {"type": "string"},
            "setting": {"type": "string", "enum": list(SETTINGS)},
            "hook": {
                "type": "object",
                "properties": {
                    "when": {"type": "string", "enum": list(HOOK_WHENS)},
                    "room": {"type": "string", "enum": ["", *room_ids]},
                    "npcName": {"type": "string"},
                    "figureHint": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["when", "room", "npcName", "figureHint", "text"],
                "additionalProperties": False,
            },
            "gateText": {"type": "string"},
            "start": {"type": "string"},
            "passages": {"type": "array", "items": passage},
            "terminals": {"type": "array", "items": terminal},
            "retry": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "costText": {"type": "string"},
                },
                "required": ["from", "to", "costText"],
                "additionalProperties": False,
            },
        },
        "required": ["id", "kind", "title", "setting", "hook", "gateText", "start", "passages", "terminals", "retry"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"sideQuests": {"type": "array", "items": side_quest}},
        "required": ["sideQuests"],
        "additionalProperties": False,
    }


def to_canonical_side_quests(payload: dict) -> list:
    """Array-with-id wire shape -> {id: node} dicts; empty sentinels
    -> absent. Idempotent on already-canonical input."""
    out = []
    for sq in payload.get("sideQuests", []) or []:
        sq = dict(sq)
        passages = sq.get("passages") or []
        if isinstance(passages, list):
            sq["passages"] = {p.get("id"): {k: v for k, v in p.items() if k != "id"} for p in passages if isinstance(p, dict)}
        terminals = sq.get("terminals") or []
        if isinstance(terminals, list):
            sq["terminals"] = {t.get("id"): {k: v for k, v in t.items() if k != "id"} for t in terminals if isinstance(t, dict)}
        retry = sq.get("retry") or {}
        sq["retry"] = retry if retry.get("from") else None
        for passage in sq["passages"].values():
            for choice in passage.get("choices", []) or []:
                test = choice.get("test") or {}
                if not test.get("kind") or test.get("kind") == "none":
                    choice["test"] = None
        out.append(sq)
    return out
