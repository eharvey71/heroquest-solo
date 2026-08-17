"""Cloud Functions entry points for the HeroQuest Zargon app.

Two responsibilities live here, kept strictly separate (see CLAUDE.md):

1. Quest generation (generate_quest): prompt build -> LLM call -> validate
   -> auto-repair -> retry (max 3) -> Firestore write. The client never
   sees an unvalidated quest.
2. The Zargon rules engine (movement, target choice, combat resolution):
   deterministic code only. The LLM is never in the rules path.

The Zargon engine (movement, target choice, combat) is not implemented
yet — that's a later task.
"""

import anthropic
from firebase_admin import firestore, initialize_app
from firebase_functions import https_fn, options
from firebase_functions.params import SecretParam

from generator import GenerationResult, QuestGenerationFailed, QuestGenerationRefused, generate_quest as run_generation
from validator.catalogs import load_catalogs

initialize_app()

# All callable functions default to this region; change once the owner
# picks a home region for the project.
options.set_global_options(region="us-central1")

ANTHROPIC_API_KEY = SecretParam("ANTHROPIC_API_KEY")

# Loaded once per instance (board/monster/furniture data never changes at
# runtime) rather than re-reading the JSON files on every invocation.
_catalogs = load_catalogs()

VALID_HERO_COUNTS = {1, 2, 3, 4}
VALID_DIFFICULTIES = {"standard", "hard"}
VALID_SIZES = {"short", "full"}


@https_fn.on_call()
def health_check(req: https_fn.CallableRequest) -> dict:
    """Trivial callable to confirm the Functions deploy pipeline works."""
    return {"status": "ok", "service": "heroquest-zargon"}


def _coords_to_maps(value):
    """Firestore rejects arrays whose direct elements are also arrays
    ("Property array contains an invalid nested entity") — hit in
    practice on `doors[].squares` ([[x1,y1],[x2,y2]]) and
    `blockedSquares` ([[x,y],...]). Convert every [x,y] coordinate pair
    to {"x": x, "y": y} so those become arrays-of-maps, which Firestore
    allows. This only runs at the Firestore write boundary — the
    canonical [x,y] array format (validator, fixtures, quest-schema.md)
    is untouched everywhere else.
    """
    if isinstance(value, list):
        if len(value) == 2 and all(isinstance(v, int) for v in value):
            return {"x": value[0], "y": value[1]}
        return [_coords_to_maps(v) for v in value]
    if isinstance(value, dict):
        return {k: _coords_to_maps(v) for k, v in value.items()}
    return value


def _parse_generation_params(data) -> dict:
    if not isinstance(data, dict):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="request data must be an object"
        )

    hero_count = data.get("heroCount")
    if hero_count not in VALID_HERO_COUNTS:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            message=f"heroCount must be one of {sorted(VALID_HERO_COUNTS)}",
        )

    difficulty = data.get("difficulty", "standard")
    if difficulty not in VALID_DIFFICULTIES:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            message=f"difficulty must be one of {sorted(VALID_DIFFICULTIES)}",
        )

    size = data.get("size", "full")
    if size not in VALID_SIZES:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message=f"size must be one of {sorted(VALID_SIZES)}"
        )

    theme = data.get("theme")
    if theme is not None and not isinstance(theme, str):
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="theme must be a string")

    params = {"heroCount": hero_count, "difficulty": difficulty, "size": size}
    if theme:
        params["theme"] = theme
    return params


# Generous timeout: up to 3 LLM round trips at high effort (observed
# ~100s each). Default callable timeout (60s) isn't enough for a single
# high-effort call, let alone the retry loop.
@https_fn.on_call(secrets=[ANTHROPIC_API_KEY], timeout_sec=480, memory=options.MemoryOption.MB_512)
def generate_quest(req: https_fn.CallableRequest) -> dict:
    """Generate a new quest, validate it, and write it to Firestore.

    Auth-gated here because callable functions do NOT inherit the
    Firestore auth rule (that only guards direct client reads/writes) —
    without this check, an unauthenticated caller could trigger paid LLM
    calls. See design/quest-generator-design.md section 4 for the
    generate -> validate -> repair -> retry pipeline this runs.
    """
    if req.auth is None:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to generate a quest"
        )

    params = _parse_generation_params(req.data)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY.value)

    try:
        result: GenerationResult = run_generation(params, client, _catalogs)
    except QuestGenerationRefused as e:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            message="the quest generator declined this request",
            details={"stopDetails": str(e.stop_details)},
        ) from e
    except QuestGenerationFailed as e:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION,
            message=f"quest failed validation after {e.attempts} attempts",
            details={"errors": e.errors},
        ) from e

    doc_ref = firestore.client().collection("quests").document()
    doc_ref.set(
        {
            **_coords_to_maps(result.quest),
            "generationParams": params,
            "validationWarnings": result.validation.warnings,
            "attempts": result.attempts,
            "createdAt": firestore.SERVER_TIMESTAMP,
        }
    )

    return {"questId": doc_ref.id}
