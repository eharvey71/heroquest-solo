"""Thin wrapper around the Anthropic Messages API for quest generation.

Uses output_config.format (structured outputs) so the API guarantees the
response is valid JSON matching the schema — no markdown fences, no
free-form prose to strip. `client` is passed in rather than constructed
here so tests can inject a fake with a `.messages.create` method instead
of hitting the network.
"""

from __future__ import annotations

import json

MODEL = "claude-opus-4-8"
# Adaptive thinking draws from the same max_tokens budget as the JSON
# output, so this needs real headroom above the ~2-4K a typical quest
# body costs. Still comfortably under the ~16K non-streaming SDK-timeout
# risk threshold.
MAX_TOKENS = 12000


class QuestGenerationRefused(Exception):
    """The model declined to generate a quest (safety refusal)."""

    def __init__(self, stop_details):
        self.stop_details = stop_details
        super().__init__(f"LLM refused to generate a quest: {stop_details}")


class QuestGenerationTruncated(Exception):
    """The response was cut off by max_tokens before valid JSON completed."""

    def __init__(self, stop_reason):
        self.stop_reason = stop_reason
        super().__init__(f"LLM response truncated (stop_reason={stop_reason}) before valid JSON completed")


def call_llm(client, system_prompt: str, user_message: str, schema: dict) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": schema},
        },
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    if response.stop_reason == "refusal":
        raise QuestGenerationRefused(response.stop_details)

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise QuestGenerationRefused(None)

    try:
        quest = json.loads(text)
    except json.JSONDecodeError as e:
        # In practice a decode failure here means truncation, regardless
        # of the exact stop_reason label — structured outputs otherwise
        # guarantees schema-valid JSON.
        raise QuestGenerationTruncated(response.stop_reason) from e

    return _to_canonical_shape(quest)


def _to_canonical_shape(quest: dict) -> dict:
    """The wire format (see schema.py) represents `rooms` as an array with
    a `roomId` on each entry, to stay under the structured-outputs
    optional-parameter limit. Converts it to the `{roomId: room}` dict
    shape the validator, fixtures, and quest-schema.md all use — nothing
    downstream of this function needs to know the wire format exists.
    """
    rooms_list = quest.get("rooms", [])
    rooms_dict = {}
    for room in rooms_list:
        room = dict(room)
        room_id = room.pop("roomId", None)
        if room_id is not None:
            rooms_dict[room_id] = room
    quest["rooms"] = rooms_dict
    return quest
