"""Generation pipeline per design/quest-generator-design.md section 4:

    params -> build prompt -> LLM (JSON mode) -> parse
      -> auto-repair trivial issues -> VALIDATE (code)
                        -> pass -> return
                        -> fail -> retry with error list appended (max 3)

The Cloud Function (functions/main.py) is the only caller that writes to
Firestore — this module just produces a validated quest or raises with the
raw validator errors, matching "client never sees an unvalidated quest."
"""

from __future__ import annotations

from dataclasses import dataclass

from validator.catalogs import Catalogs, load_catalogs
from validator.core import validate_quest
from validator.result import ValidationResult

from .client import QuestGenerationTruncated, call_llm
from .fence import apply_fence
from .prompt import build_retry_message, build_system_prompt, build_user_message, pick_stairway_room
from .repair import apply_auto_repair
from .schema import build_quest_json_schema

TRUNCATION_RETRY_HINT = (
    "the previous response was cut off by the token limit before completing valid JSON — "
    "return a shorter quest (fewer populated rooms, or shorter backstory/revealText/completionText)"
)

MAX_ATTEMPTS = 3


@dataclass
class GenerationResult:
    quest: dict
    validation: ValidationResult
    attempts: int


class QuestGenerationFailed(Exception):
    """Raised when the quest still fails validation after MAX_ATTEMPTS.

    Per the design doc: "After 3 failures, surface the raw errors in the
    UI rather than silently looping" — callers should show `errors`
    directly, not retry again themselves.
    """

    def __init__(self, errors: list, attempts: int):
        self.errors = errors
        self.attempts = attempts
        super().__init__(f"quest generation failed after {attempts} attempts: {errors}")


def _fence_play_area(quest: dict, params: dict, catalogs: Catalogs, passed: ValidationResult) -> ValidationResult:
    """Cordons the unused parts of the board off (generator/fence.py),
    then re-validates. The fence is computed to preserve reachability, so
    this second pass should never fail -- but a quest that already
    validated must not be broken by a cosmetic step, so a failure puts
    the original blockedSquares back and keeps the quest as it was.
    """
    original = quest.get("blockedSquares", [])
    apply_fence(quest, catalogs)
    fenced = validate_quest(quest, params, catalogs)
    if fenced.ok:
        return fenced
    quest["blockedSquares"] = original
    return passed


def generate_quest(params: dict, client, catalogs: Catalogs | None = None) -> GenerationResult:
    """params: {"heroCount": 1-4, "difficulty": "standard"|"hard",
    "size": "short"|"full", "theme": str}. `client` is an Anthropic
    client (or anything with a matching `.messages.create`) — injected so
    tests can pass a fake instead of calling the real API.
    """
    catalogs = catalogs or load_catalogs()
    schema = build_quest_json_schema(catalogs)
    # Picked once per generation call, not re-picked per retry -- the
    # retry loop's contract is "fix ONLY these errors," so the starting
    # room must stay fixed across attempts within one generate_quest call.
    stairway_room = pick_stairway_room(catalogs)
    system_prompt = build_system_prompt(params, catalogs, stairway_room)
    validation_params = {**params, "stairwayRoom": stairway_room}

    message = build_user_message(params)
    last_errors = ["no attempt completed"]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            quest = call_llm(client, system_prompt, message, schema)
        except QuestGenerationTruncated:
            last_errors = [TRUNCATION_RETRY_HINT]
            message = build_retry_message(last_errors)
            continue

        apply_auto_repair(quest, params, catalogs)
        result = validate_quest(quest, validation_params, catalogs)
        if result.ok:
            result = _fence_play_area(quest, validation_params, catalogs, result)
            return GenerationResult(quest=quest, validation=result, attempts=attempt)
        last_errors = result.errors
        message = build_retry_message(last_errors)

    raise QuestGenerationFailed(errors=last_errors, attempts=MAX_ATTEMPTS)
