"""Thin wrapper around the Anthropic Messages API for quest generation.

NO structured outputs (output_config.format), deliberately, since Aug
2026: the server's grammar compiler started rejecting this quest schema
with "The compiled grammar is too large" at a budget so tight that the
pre-chaos-spells schema saturated it EXACTLY -- live-API bisection
(tools/repro_grammar.py) showed every structural addition failing, even
two plain optional strings, on claude-opus-4-8, claude-opus-5 and
claude-sonnet-5 alike, while byte-size padding and enum-stripping
changed nothing. Fighting for grammar headroom would put every future
schema field back on that knife edge.

Instead the full JSON Schema (all enums intact) is embedded in the
system prompt as an instruction, and the response is parsed here: the
first "{" to the last "}", so a stray markdown fence costs nothing. The
guarantee structured outputs provided was only ever shape -- the
validator + auto-repair + retry loop (generator/core.py) has always
been the real gate ("client never sees an unvalidated quest"), and a
malformed response is simply one more retryable attempt
(QuestGenerationMalformed), exactly like a validation failure.

`client` is passed in rather than constructed here so tests can inject
a fake with a `.messages.create` method instead of hitting the network.
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


class QuestGenerationMalformed(Exception):
    """The response finished but wasn't parseable JSON. Retryable in
    core.py's loop, same as a validation failure."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"LLM response was not valid JSON: {detail}")


SCHEMA_INSTRUCTION = """

## OUTPUT FORMAT

Respond with ONE JSON object and nothing else -- no prose before or
after it, no markdown fences. It MUST conform exactly to this JSON
Schema (every "required" field present, no properties beyond those
listed, enum fields limited to their listed values):

"""


def extract_json(text: str) -> dict:
    """The first "{" to the last "}" -- tolerates a stray fence or a
    sentence of preamble without needing structured outputs."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise QuestGenerationMalformed("no JSON object found in the response")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise QuestGenerationMalformed(str(e)) from e


def call_llm(client, system_prompt: str, user_message: str, schema: dict) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=system_prompt + SCHEMA_INSTRUCTION + json.dumps(schema, indent=2),
        messages=[{"role": "user", "content": user_message}],
    )

    if response.stop_reason == "refusal":
        raise QuestGenerationRefused(response.stop_details)

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        raise QuestGenerationRefused(None)

    try:
        quest = extract_json(text)
    except QuestGenerationMalformed:
        # A response the token limit cut off is unparseable too, but it
        # needs the "make it shorter" retry hint, not the "emit valid
        # JSON" one.
        if response.stop_reason == "max_tokens":
            raise QuestGenerationTruncated(response.stop_reason) from None
        raise

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
