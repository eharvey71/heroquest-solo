"""Builds the JSON Schema passed to the LLM via output_config.format, so the
API guarantees schema-valid JSON back (see claude-api skill: structured
outputs). This only enforces *shape* (right fields, right types, known
enums) — the validator (functions/validator/) still owns every geometry,
reachability, and balance rule the schema can't express.

Uses $defs/$ref for every reused shape (room, monster, furniture, trap).
Anthropic's structured-outputs grammar compiler caps total OPTIONAL
parameters at 24 across the whole schema. Two things blew past that
before landing on this shape:

1. Inlining the room/monster/furniture schemas literally into each of
   the 22 room properties (instead of $ref) multiplied the count to 358.
2. Even with $ref, representing "which of the 22 rooms are populated" as
   `rooms: {R1?: ..., R2?: ..., ...}` — one optional property per room id
   — cost 22 of the budget by itself (28 total), since most quests only
   populate a handful of rooms. `additionalProperties: false` rules out
   a plain dynamic map as the fix.

The fix: `rooms` is an ARRAY of room objects, each carrying its own
`roomId` (required, enum-constrained to the real room ids). A dynamic
count expressed as array length costs nothing in this metric — only
object shape does. generator/client.py converts the array back to the
canonical `{roomId: room}` dict (what the validator, fixtures, and
quest-schema.md all expect) immediately after parsing, so this
constraint never leaks past the wire-format boundary. Total optional
count is ~10.
"""

from __future__ import annotations

from engine.chaos_spells import spell_ids as chaos_spell_ids_fn
from validator.catalogs import Catalogs

POS = {"type": "array", "items": {"type": "integer"}}
POS_PAIR = {"type": "array", "items": POS}


def _defs(catalogs: Catalogs, room_ids: list) -> dict:
    return {
        "monster": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "type": {"type": "string", "enum": sorted(catalogs.monsters.keys())},
                # Chaos spells are handed to "specific monsters called
                # for in the Quest notes" (the cards' own instructions).
                "spells": {"type": "array", "items": {"type": "string", "enum": chaos_spell_ids_fn()}},
                "name": {"type": "string"},
                "pos": POS,
                "overrides": {
                    "type": "object",
                    "properties": {
                        "move": {"type": "integer"},
                        "attack": {"type": "integer"},
                        "defend": {"type": "integer"},
                        "body": {"type": "integer"},
                        "mind": {"type": "integer"},
                    },
                    "required": ["move", "attack", "defend", "body", "mind"],
                    "additionalProperties": False,
                },
            },
            "required": ["id", "type", "pos"],
            "additionalProperties": False,
        },
        "furniture": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": sorted(catalogs.furniture.keys())},
                "pos": POS,
                "orientation": {"type": "string", "enum": ["N", "S", "E", "W"]},
                "contains": {
                    "type": "object",
                    "properties": {
                        # "chest_trap" is the usual case: a needle, a gas,
                        # a spring -- narrated, no tile. pit/falling_block
                        # are for the rare piece standing over one, and
                        # they DO put a tile on the board.
                        "trap": {"type": "string", "enum": ["chest_trap", "pit", "falling_block", "none"]},
                        # What springing it does, in the quest book's own
                        # voice. The app never computes trap damage --
                        # Body Points are physical -- so this text IS the
                        # effect (see engine/furniture_traps.py).
                        "trapText": {"type": "string"},
                        "treasure": {"type": "string"},
                    },
                    "required": ["trap", "treasure"],
                    "additionalProperties": False,
                },
            },
            "required": ["type", "pos"],
            "additionalProperties": False,
        },
        "trap": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["pit", "falling_block", "spear"]},
                "pos": POS,
            },
            "required": ["type", "pos"],
            "additionalProperties": False,
        },
        "door": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "squares": POS_PAIR,
                "state": {"type": "string", "enum": ["open", "closed", "secret"]},
            },
            "required": ["id", "squares", "state"],
            "additionalProperties": False,
        },
        "room": {
            "type": "object",
            "properties": {
                "roomId": {"type": "string", "enum": room_ids},
                "revealText": {"type": "string"},
                "monsters": {"type": "array", "items": {"$ref": "#/$defs/monster"}},
                "furniture": {"type": "array", "items": {"$ref": "#/$defs/furniture"}},
                "traps": {"type": "array", "items": {"$ref": "#/$defs/trap"}},
            },
            "required": ["roomId", "revealText", "monsters", "furniture", "traps"],
            "additionalProperties": False,
        },
        "targetRoomId": {"type": "string", "enum": room_ids},
    }


def build_quest_json_schema(catalogs: Catalogs) -> dict:
    room_ids = sorted(catalogs.board.room_ids)
    defs = _defs(catalogs, room_ids)

    return {
        "type": "object",
        "$defs": defs,
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "backstory": {"type": "string"},
            "objective": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["kill_boss", "find_artifact", "reach_exit", "rescue"],
                    },
                    "description": {"type": "string"},
                    "target": {
                        "type": "object",
                        "properties": {
                            "monsterId": {"type": "string"},
                            "room": {"$ref": "#/$defs/targetRoomId"},
                        },
                        "additionalProperties": False,
                    },
                    "secretPathHint": {
                        "type": "object",
                        "properties": {
                            "room": {"$ref": "#/$defs/targetRoomId"},
                            "text": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["type", "description", "target"],
                "additionalProperties": False,
            },
            "wanderingMonster": {"type": "string", "enum": sorted(catalogs.monsters.keys())},
            "stairway": {
                "type": "object",
                "properties": {
                    "room": {"$ref": "#/$defs/targetRoomId"},
                    "pos": POS,
                },
                "required": ["room", "pos"],
                "additionalProperties": False,
            },
            "blockedSquares": {"type": "array", "items": POS},
            # Where the Escape card teleports its caster: "a secret
            # destination known only to Zargon ... marked on the Quest
            # Map". Required only if some monster carries that card.
            "escapeDestination": POS,
            "startingRoom": {"type": "string", "const": "stairway"},
            "doors": {"type": "array", "items": {"$ref": "#/$defs/door"}},
            "corridorTraps": {"type": "array", "items": {"$ref": "#/$defs/trap"}},
            "rooms": {"type": "array", "items": {"$ref": "#/$defs/room"}},
            "completionText": {"type": "string"},
        },
        "required": [
            "id", "title", "backstory", "objective", "wanderingMonster",
            "stairway", "blockedSquares", "startingRoom", "doors", "rooms",
            "completionText",
        ],
        "additionalProperties": False,
    }
