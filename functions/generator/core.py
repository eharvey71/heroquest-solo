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

from .client import QuestGenerationMalformed, QuestGenerationTruncated, call_llm
from .fence import apply_fence
from .prompt import build_retry_message, build_system_prompt, build_user_message, pick_stairway_room
from .repair import apply_auto_repair
from .schema import build_quest_json_schema

TRUNCATION_RETRY_HINT = (
    "the previous response was cut off by the token limit before completing valid JSON — "
    "return a shorter quest (fewer populated rooms, or shorter backstory/revealText/completionText)"
)

MALFORMED_RETRY_HINT = (
    "the previous response was not valid JSON -- respond with ONLY the JSON object, "
    "no prose and no markdown fences"
)

MAX_ATTEMPTS = 3


def notify(on_progress, stage: str, detail: str) -> None:
    """Live status for the setup screen (main._JobProgress writes it to
    a Firestore doc the browser listens to). Optional and best-effort:
    generation never depends on it, and tests pass nothing."""
    if on_progress is not None:
        on_progress(stage, detail)


def summarize_errors(errors: list, limit: int = 2, width: int = 90) -> str:
    """The first couple of validator errors, clipped, for a status line."""
    shown = [str(e)[:width] + ("…" if len(str(e)) > width else "") for e in errors[:limit]]
    more = len(errors) - len(shown)
    return "; ".join(shown) + (f"; and {more} more" if more > 0 else "")


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


def generate_quest(params: dict, client, catalogs: Catalogs | None = None, on_progress=None) -> GenerationResult:
    """params: {"heroCount": 1-4, "difficulty": "standard"|"hard",
    "size": "short"|"full", "theme": str}. `client` is an Anthropic
    client (or anything with a matching `.messages.create`) — injected so
    tests can pass a fake instead of calling the real API. `on_progress`
    (stage, detail) is called at each step for the setup screen's live
    status; see notify().
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
        notify(
            on_progress,
            "writing",
            f"Writing the quest -- attempt {attempt} of {MAX_ATTEMPTS}. The model is thinking; "
            f"this is the long part (usually 1-2 minutes).",
        )
        try:
            quest = call_llm(client, system_prompt, message, schema)
        except QuestGenerationTruncated:
            last_errors = [TRUNCATION_RETRY_HINT]
            message = build_retry_message(last_errors)
            notify(on_progress, "retrying", f"Attempt {attempt}: the answer was cut off by the length limit. Asking for a shorter quest.")
            continue
        except QuestGenerationMalformed:
            last_errors = [MALFORMED_RETRY_HINT]
            message = build_retry_message(last_errors)
            notify(on_progress, "retrying", f"Attempt {attempt}: the answer wasn't valid JSON. Asking again.")
            continue

        notify(on_progress, "validating", "Checking the quest: geometry, reachability, monster budget, artifacts.")
        apply_auto_repair(quest, params, catalogs)
        result = validate_quest(quest, validation_params, catalogs)
        if result.ok:
            notify(on_progress, "fencing", "The quest passed every check. Fencing the play area with blocked-square tiles.")
            result = _fence_play_area(quest, validation_params, catalogs, result)
            return GenerationResult(quest=quest, validation=result, attempts=attempt)
        last_errors = result.errors
        message = build_retry_message(last_errors)
        notify(
            on_progress,
            "retrying",
            f"Attempt {attempt} failed {len(last_errors)} check(s): {summarize_errors(last_errors)}. Asking for a fix.",
        )

    raise QuestGenerationFailed(errors=last_errors, attempts=MAX_ATTEMPTS)
