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
a fake with a `.messages.create` (or `.messages.stream`) method instead
of hitting the network.

The calls STREAM (client.messages.stream + get_final_message), for one
reason: headroom. Adaptive thinking draws from the same max_tokens
budget as the JSON output, and at high effort the thinking alone can
run to many thousands of tokens. At the old 12000 cap the model was
sometimes cut off while still thinking -- a response with thinking
blocks and no text at all -- which this module then reported as a
REFUSAL ("the quest generator declined this request", with no
details, because stop_details is only ever set on a real refusal
stop). Live play hit that twice before it was understood. Streaming is
what allows a large max_tokens: the SDK refuses a non-streaming request
it estimates at over ~10 minutes, and a long think would idle the
connection anyway.
"""

from __future__ import annotations

import json
import logging

MODEL = "claude-opus-4-8"
# Thinking + JSON. A full quest body is ~4-8K tokens; the rest is room
# for the model to think at high effort without being cut off mid-
# thought. A ceiling, not a target -- see the module docstring.
MAX_TOKENS = 32000


class QuestGenerationRefused(Exception):
    """The model declined to generate a quest (safety refusal), or sent
    back a response with no text in it for a reason other than the
    length limit. stop_details is a plain string either way: a real
    refusal's category and explanation, or a description of what came
    back -- never None, so the error is diagnosable from the client."""

    def __init__(self, stop_details):
        self.stop_details = stop_details
        super().__init__(f"LLM refused to generate a quest: {stop_details}")


def describe_stop_details(stop_details) -> str:
    """The API's stop_details object (category + explanation) as one
    line. Populated only when stop_reason is "refusal"."""
    if stop_details is None:
        return "refusal with no details"
    category = getattr(stop_details, "category", None)
    explanation = getattr(stop_details, "explanation", None)
    if category is None and explanation is None and isinstance(stop_details, dict):
        category, explanation = stop_details.get("category"), stop_details.get("explanation")
    parts = [str(p) for p in (category, explanation) if p]
    return ": ".join(parts) if parts else str(stop_details)


def final_message(client, **kwargs):
    """One streamed request, returned as the complete message. Falls
    back to a plain create for a client that has no stream method (the
    tests' simplest fakes)."""
    stream_fn = getattr(client.messages, "stream", None)
    if stream_fn is None:
        return client.messages.create(**kwargs)
    with stream_fn(**kwargs) as stream:
        return stream.get_final_message()


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
    return _to_canonical_shape(call_llm_raw(client, system_prompt, user_message, schema))


def call_llm_raw(client, system_prompt: str, user_message: str, schema: dict, *, max_tokens: int = MAX_TOKENS) -> dict:
    """One prompt-embedded-schema call, parsed to a dict and nothing
    more. call_llm adds the quest's own wire-shape conversion on top;
    generator/side_quests.py uses this directly with its own schema."""
    response = final_message(
        client,
        model=MODEL,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        system=system_prompt + SCHEMA_INSTRUCTION + json.dumps(schema, indent=2),
        messages=[{"role": "user", "content": user_message}],
    )
    usage = getattr(response, "usage", None)
    logging.info(
        "llm call: stop_reason=%s output_tokens=%s blocks=%s",
        response.stop_reason,
        getattr(usage, "output_tokens", "?"),
        [getattr(b, "type", "?") for b in response.content],
    )

    if response.stop_reason == "refusal":
        raise QuestGenerationRefused(describe_stop_details(response.stop_details))

    text = next((block.text for block in response.content if block.type == "text"), None)
    if text is None:
        # No text at all. On max_tokens that means the whole budget went
        # on thinking -- a cutoff, not a refusal, and the retry loop's
        # "shorter" hint is the right answer. Anything else is reported
        # with what came back, so it can be diagnosed from the client.
        if response.stop_reason == "max_tokens":
            raise QuestGenerationTruncated("max_tokens before any text -- the thinking used the whole budget")
        kinds = [getattr(b, "type", "?") for b in response.content]
        raise QuestGenerationRefused(f"no text in the response (stop_reason={response.stop_reason}, blocks={kinds})")

    try:
        return extract_json(text)
    except QuestGenerationMalformed:
        # A response the token limit cut off is unparseable too, but it
        # needs the "make it shorter" retry hint, not the "emit valid
        # JSON" one.
        if response.stop_reason == "max_tokens":
            raise QuestGenerationTruncated(response.stop_reason) from None
        raise


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
