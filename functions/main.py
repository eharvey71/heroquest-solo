"""Cloud Functions entry points for the HeroQuest Zargon app.

Two responsibilities live here, kept strictly separate (see CLAUDE.md):

1. Quest generation (generate_quest): prompt build -> LLM call -> validate
   -> auto-repair -> retry (max 3) -> Firestore write. The client never
   sees an unvalidated quest.
2. The Zargon rules engine (movement, target choice, combat resolution):
   deterministic code only. The LLM is never in the rules path.
   resolve_movement is the first live-game endpoint; target
   selection/combat endpoints are later tasks.
"""

import anthropic
from firebase_admin import firestore, initialize_app
from firebase_functions import https_fn, options
from firebase_functions.params import SecretParam

from engine.hero_movement import IllegalMovementError, resolve_hero_movement
from firestore_coords import from_firestore_coords, to_firestore_coords
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
            **to_firestore_coords(result.quest),
            "generationParams": params,
            "validationWarnings": result.validation.warnings,
            "attempts": result.attempts,
            "createdAt": firestore.SERVER_TIMESTAMP,
        }
    )

    return {"questId": doc_ref.id}


def _parse_movement_request(data) -> tuple[str, str, list]:
    if not isinstance(data, dict):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="request data must be an object"
        )

    game_id = data.get("gameId")
    hero_id = data.get("heroId")
    path = data.get("path")

    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")
    if not isinstance(hero_id, str) or not hero_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="heroId is required")
    if not isinstance(path, list) or not path:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="path must be a non-empty array"
        )

    return game_id, hero_id, path


@firestore.transactional
def _apply_movement(transaction, db, game_ref, hero_id, path):
    game_snap = game_ref.get(transaction=transaction)
    if not game_snap.exists:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message="game not found")
    game_state = from_firestore_coords(game_snap.to_dict())

    if game_state.get("phase") != "hero":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="it is not the hero phase"
        )

    quest_id = game_state.get("questId")
    if not quest_id:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="game has no questId"
        )
    quest_snap = db.collection("quests").document(quest_id).get(transaction=transaction)
    if not quest_snap.exists:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message="quest not found")
    quest = from_firestore_coords(quest_snap.to_dict())

    result = resolve_hero_movement(
        board=_catalogs.board, quest=quest, game_state=game_state, hero_id=hero_id, path=path
    )

    heroes = game_state.get("heroes", [])
    for h in heroes:
        if h["id"] == hero_id:
            h["pos"] = list(result.final_pos)

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    new_log_entries = [{"turn": turn, "text": line} for line in result.log]

    transaction.update(
        game_ref,
        {
            "heroes": to_firestore_coords(heroes),
            "revealed.rooms": sorted(result.revealed_rooms),
            "revealed.corridorSquares": to_firestore_coords(sorted(result.revealed_corridor_squares)),
            "trapsTriggered": sorted(result.traps_triggered),
            "log": existing_log + new_log_entries,
        },
    )

    return result


@https_fn.on_call()
def resolve_movement(req: https_fn.CallableRequest) -> dict:
    """Resolves a hero's traced movement path (from BoardView's
    onConfirmMove) against live game state: trap triggers mid-move,
    progressive fog-of-war reveal, and a hard stop at a closed door --
    opening one is its own button per CLAUDE.md's interface list, not
    something movement does automatically. See
    functions/engine/hero_movement.py for the pure resolution logic;
    this is just the Firestore read/write shell around it.
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to move a hero")

    game_id, hero_id, path = _parse_movement_request(req.data)

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    transaction = db.transaction()

    try:
        result = _apply_movement(transaction, db, game_ref, hero_id, path)
    except IllegalMovementError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message=str(e)) from e

    return {
        "finalPos": list(result.final_pos),
        "pathTaken": [list(p) for p in result.path_taken],
        "stoppedReason": result.stopped_reason,
        "stoppedAtDoorId": result.stopped_at_door_id,
        "newlyRevealedRooms": result.newly_revealed_rooms,
        "triggeredTraps": [
            {
                "trapId": t.trap_id,
                "type": t.trap_type,
                "pos": list(t.pos),
                "placementInstruction": t.placement_instruction,
            }
            for t in result.triggered_traps
        ],
        "log": result.log,
    }
