"""Cloud Functions entry points for the HeroQuest Zargon app.

Two responsibilities live here, kept strictly separate (see CLAUDE.md):

1. Quest generation (generate_quest): prompt build -> LLM call -> validate
   -> auto-repair -> retry (max 3) -> Firestore write. The client never
   sees an unvalidated quest.
2. The Zargon rules engine (movement, target choice, combat resolution):
   deterministic code only. The LLM is never in the rules path.

Live-game endpoints: create_game seeds a games/ doc from a quest;
resolve_movement, open_door (a hard movement stop resolved as its own
action), search_treasure (once per hero per room, may spawn+attack
the rulebook wandering-monster card), search_traps_and_secret_doors
(once-per-room, fully digital -- reveals what's already in the quest
data; searchType picks traps OR secret doors -- two distinct hero
actions), end_turn (flips phase hero->zargon; a lone-hero party gets two
full hero phases per turn first -- heroPhaseSegment),
roll_zargon_turn_type/resolve_zargon_turn, resolve_hero_attack, and
record_hero_defense (log-only shield reporting) operate on it
afterward. Ending a quest takes TWO stages (see
_mark_objective_if_complete): the objective is met, and then a hero
walks back to the stairway -- the rulebook only counts a quest
finished there. Every action that can advance either stage checks it:
resolve_movement, open_door and resolve_hero_attack (a monster dying
or a room becoming revealed), plus resolve_trap_action, since a jump
can land a hero on the stairs.
"""

import anthropic
from firebase_admin import firestore, initialize_app
from firebase_functions import https_fn, options
from firebase_functions.params import SecretParam

from engine.combat import record_hero_defense as record_hero_defense_engine
from engine.combat import resolve_hero_attack as resolve_hero_attack_engine
from engine.create_game import InvalidRosterError, build_initial_game_state
from engine.doors import DoorNotFoundError, InvalidDoorOpenError, resolve_open_door
from engine.end_turn import NotHeroPhaseError, resolve_end_turn
from engine.hero_movement import IllegalMovementError, resolve_hero_movement
from engine.objective import check_objective_complete, hero_on_stairway
from engine.spell import InvalidSpellError, resolve_hero_spell
from engine.targeting import needs_cunning_target_prompt, roll_turn_type
from engine.trap_search import InvalidTrapSearchError
from engine.trap_search import RoomNotFoundError as TrapSearchRoomNotFoundError
from engine.trap_action import InvalidTrapActionError, TRAP_ACTIONS, resolve_trap_action
from engine.trap_search import SEARCH_TYPES, resolve_trap_search
from engine.treasure import InvalidTreasureSearchError, RoomNotFoundError, resolve_treasure_search
from engine.zargon_turn import _monster_defs, resolve_zargon_turn as resolve_zargon_turn_engine
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


def _parse_create_game_request(data) -> tuple[str, list]:
    if not isinstance(data, dict):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="request data must be an object"
        )

    quest_id = data.get("questId")
    heroes = data.get("heroes")

    if not isinstance(quest_id, str) or not quest_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="questId is required")
    if not isinstance(heroes, list) or not (1 <= len(heroes) <= 4):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="heroes must be an array of 1-4 entries"
        )
    ids = set()
    for h in heroes:
        if not isinstance(h, dict) or not isinstance(h.get("id"), str) or not h["id"]:
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="each hero needs a string 'id'"
            )
        if h["id"] in ids:
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message=f"duplicate hero id '{h['id']}'"
            )
        ids.add(h["id"])

    return quest_id, heroes


@https_fn.on_call()
def create_game(req: https_fn.CallableRequest) -> dict:
    """Seeds a new games/ doc from a generated quest: heroes placed on
    the stairway, the full monster roster loaded at full body points
    (fog of war governs what's actually shown, not what's tracked),
    only the stairway room revealed, phase="hero", turn=1. See
    functions/engine/create_game.py for the pure initialization logic.
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to start a game")

    quest_id, heroes = _parse_create_game_request(req.data)

    db = firestore.client()
    quest_snap = db.collection("quests").document(quest_id).get()
    if not quest_snap.exists:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message="quest not found")
    quest = from_firestore_coords(quest_snap.to_dict())

    try:
        game_state = build_initial_game_state(quest=quest, catalogs=_catalogs, heroes=heroes)
    except InvalidRosterError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message=str(e)) from e

    game_state["questId"] = quest_id
    doc_ref = db.collection("games").document()
    doc_ref.set({**to_firestore_coords(game_state), "createdAt": firestore.SERVER_TIMESTAMP})

    return {"gameId": doc_ref.id}


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


def _load_game(game_ref, transaction=None) -> dict:
    """Shared read: just the live game doc. Used by endpoints that don't
    need the quest it references (e.g. end_turn's phase flip).
    """
    game_snap = game_ref.get(transaction=transaction) if transaction is not None else game_ref.get()
    if not game_snap.exists:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message="game not found")
    return from_firestore_coords(game_snap.to_dict())


def _load_game_and_quest(db, game_ref, transaction=None) -> tuple[dict, dict]:
    """Shared read: a live game doc plus the quest it references. Used
    by every endpoint that touches game state, transactional or not.
    """
    game_state = _load_game(game_ref, transaction)

    quest_id = game_state.get("questId")
    if not quest_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="game has no questId")
    quest_ref = db.collection("quests").document(quest_id)
    quest_snap = quest_ref.get(transaction=transaction) if transaction is not None else quest_ref.get()
    if not quest_snap.exists:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message="quest not found")
    quest = from_firestore_coords(quest_snap.to_dict())

    return game_state, quest


def _mark_objective_if_complete(quest: dict, game_state: dict, updates: dict, log_entries: list, turn: int) -> bool:
    """Advances the two-stage ending against `game_state` (the caller
    must have already applied this action's changes to the LOCAL
    game_state dict -- new revealed rooms, a monster's flipped alive
    flag, a hero's new position -- before calling this).

    Stage 1: the objective is met -> objectiveComplete, and the party is
    told to head back. Stage 2: a hero reaches the stairway -> status
    "complete". The rulebook ends a quest at the stairway, not at the
    objective (engine/objective.py). Appends its own log lines for both
    stages; returns True only when this call finished the whole quest.
    """
    if game_state.get("status") == "complete":
        return False

    objective_done = game_state.get("objectiveComplete") or check_objective_complete(quest, game_state)
    if not objective_done:
        return False

    if not game_state.get("objectiveComplete"):
        updates["objectiveComplete"] = True
        game_state["objectiveComplete"] = True
        log_entries.append(
            {
                "turn": turn,
                "text": (
                    f"{quest.get('objective', {}).get('description', 'The objective')} -- done! "
                    f"Now get back to the stairway; the quest is only safely finished there."
                ),
            }
        )

    if not hero_on_stairway(quest, game_state):
        return False

    updates["status"] = "complete"
    log_entries.append({"turn": turn, "text": quest.get("completionText", "The heroes escape with the quest complete!")})
    return True


@firestore.transactional
def _apply_movement(transaction, db, game_ref, hero_id, path):
    game_state, quest = _load_game_and_quest(db, game_ref, transaction)

    if game_state.get("phase") != "hero":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="it is not the hero phase"
        )

    result = resolve_hero_movement(
        board=_catalogs.board, catalogs=_catalogs, quest=quest, game_state=game_state, hero_id=hero_id, path=path
    )

    heroes = game_state.get("heroes", [])
    for h in heroes:
        if h["id"] == hero_id:
            h["pos"] = list(result.final_pos)
    game_state["revealed"]["rooms"] = sorted(result.revealed_rooms)

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    new_log_entries = [{"turn": turn, "text": line} for line in result.log]

    updates = {
        "heroes": to_firestore_coords(heroes),
        "revealed.rooms": sorted(result.revealed_rooms),
        "revealed.corridorSquares": to_firestore_coords(sorted(result.revealed_corridor_squares)),
        "trapsTriggered": sorted(result.traps_triggered),
        # trapsFound is deliberately NOT written here: movement never adds
        # to it, and the stored value is a {trapId: {type,pos}} map the
        # engine only reads ids from -- rewriting it from a set of ids
        # would throw the positions away.
        "collapsedSquares": to_firestore_coords(sorted(result.collapsed_squares)),
    }
    _mark_objective_if_complete(quest, game_state, updates, new_log_entries, turn)
    updates["log"] = existing_log + new_log_entries

    transaction.update(game_ref, updates)

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


@firestore.transactional
def _apply_end_turn(transaction, game_ref):
    game_state = _load_game(game_ref, transaction)
    result = resolve_end_turn(game_state)

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    new_log_entries = [{"turn": turn, "text": line} for line in result.log]

    transaction.update(
        game_ref,
        {"phase": result.new_phase, "heroPhaseSegment": result.new_segment, "log": existing_log + new_log_entries},
    )
    return result


@https_fn.on_call()
def end_turn(req: https_fn.CallableRequest) -> dict:
    """The heroes are done acting -- flips phase from "hero" to
    "zargon" so roll_zargon_turn_type/resolve_zargon_turn become
    reachable. Exception: a lone-hero party's first end-turn of the
    game turn stays in the hero phase and advances heroPhaseSegment to
    2 (the 1-hero-2-actions balance rule) -- see
    functions/engine/end_turn.py for the pure logic.
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to play")

    data = req.data if isinstance(req.data, dict) else {}
    game_id = data.get("gameId")
    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    transaction = db.transaction()

    try:
        result = _apply_end_turn(transaction, game_ref)
    except NotHeroPhaseError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message=str(e)) from e

    return {"phase": result.new_phase, "heroPhaseSegment": result.new_segment}


@firestore.transactional
def _apply_open_door(transaction, db, game_ref, hero_id, door_id):
    game_state, quest = _load_game_and_quest(db, game_ref, transaction)

    if game_state.get("phase") != "hero":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="it is not the hero phase"
        )

    result = resolve_open_door(
        board=_catalogs.board, quest=quest, game_state=game_state, hero_id=hero_id, door_id=door_id
    )

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    new_log_entries = [{"turn": turn, "text": line} for line in result.log]
    updates = {f"doors.{door_id}": result.new_state}

    if result.revealed_room is not None:
        revealed_rooms = set(game_state.get("revealed", {}).get("rooms", []))
        revealed_rooms.add(result.revealed_room)
        updates["revealed.rooms"] = sorted(revealed_rooms)
        game_state["revealed"]["rooms"] = sorted(revealed_rooms)

    _mark_objective_if_complete(quest, game_state, updates, new_log_entries, turn)
    updates["log"] = existing_log + new_log_entries

    transaction.update(game_ref, updates)
    return result


@https_fn.on_call()
def open_door(req: https_fn.CallableRequest) -> dict:
    """Opens a closed door the hero is standing at -- its own button
    per CLAUDE.md's interface list, separate from movement (which hard
    stops at a closed door rather than auto-opening it). Reveals the
    far room immediately, matching how a human Zargon populates a room
    as soon as the door swings open. See functions/engine/doors.py for
    the pure resolution logic (including why secret doors are
    explicitly out of scope for this button).
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to play")

    data = req.data if isinstance(req.data, dict) else {}
    game_id = data.get("gameId")
    hero_id = data.get("heroId")
    door_id = data.get("doorId")

    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")
    if not isinstance(hero_id, str) or not hero_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="heroId is required")
    if not isinstance(door_id, str) or not door_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="doorId is required")

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    transaction = db.transaction()

    try:
        result = _apply_open_door(transaction, db, game_ref, hero_id, door_id)
    except DoorNotFoundError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message=str(e)) from e
    except InvalidDoorOpenError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message=str(e)) from e

    return {
        "doorId": result.door_id,
        "newState": result.new_state,
        "revealedRoom": result.revealed_room,
        "placementInstruction": result.placement_instruction,
        "log": result.log,
    }


def _next_wandering_monster_id(existing_ids: set) -> str:
    """Both wandering-monster mechanics (turn-roll and treasure-card,
    CLAUDE.md's "Zargon engine details") assign fresh ids from the same
    "W{n}" namespace -- they're both spawns outside the quest's static
    monster roster.
    """
    i = 1
    while f"W{i}" in existing_ids:
        i += 1
    return f"W{i}"


@firestore.transactional
def _apply_search_treasure(transaction, db, game_ref, hero_id, room_id, wandering_monster_drawn):
    game_state, quest = _load_game_and_quest(db, game_ref, transaction)

    if game_state.get("phase") != "hero":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="it is not the hero phase"
        )

    result = resolve_treasure_search(
        board=_catalogs.board,
        catalogs=_catalogs,
        quest=quest,
        game_state=game_state,
        hero_id=hero_id,
        room_id=room_id,
        wandering_monster_drawn=wandering_monster_drawn,
    )

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    new_log_entries = [{"turn": turn, "text": line} for line in result.log]
    updates: dict = {
        f"searched.{room_id}.treasureBy": firestore.ArrayUnion([hero_id]),
        "log": existing_log + new_log_entries,
    }

    if result.spawned_monster:
        existing_ids = set(game_state.get("monsters", {}).keys())
        new_monster_id = _next_wandering_monster_id(existing_ids)
        spawn = result.spawned_monster
        catalog_entry = _catalogs.monsters.get(spawn["type"], {})
        updates[f"monsters.{new_monster_id}"] = to_firestore_coords(
            {
                "type": spawn["type"],
                "pos": list(spawn["pos"]),
                "currentBody": catalog_entry.get("body", 1),
                "alive": True,
            }
        )

    transaction.update(game_ref, updates)
    return result


@https_fn.on_call()
def search_treasure(req: https_fn.CallableRequest) -> dict:
    """The owner draws from the real treasure deck (entirely physical
    -- the app never learns what was drawn) and reports only whether
    the wandering-monster card came up, via wanderingMonsterDrawn.
    Enforces one treasure search per hero per room (1989 rulebook,
    see engine/treasure.py). If the card was
    drawn, spawns the quest's wandering-monster type adjacent to the
    searching hero and rolls its attack immediately -- rulebook-
    mandated, see engine/treasure.py. The hero then defends with their
    own physical dice and reports shields via record_hero_defense, same
    as any other monster attack.
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to play")

    data = req.data if isinstance(req.data, dict) else {}
    game_id = data.get("gameId")
    hero_id = data.get("heroId")
    room_id = data.get("roomId")
    wandering_monster_drawn = data.get("wanderingMonsterDrawn", False)

    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")
    if not isinstance(hero_id, str) or not hero_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="heroId is required")
    if not isinstance(room_id, str) or not room_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="roomId is required")
    if not isinstance(wandering_monster_drawn, bool):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="wanderingMonsterDrawn must be a boolean"
        )

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    transaction = db.transaction()

    try:
        result = _apply_search_treasure(transaction, db, game_ref, hero_id, room_id, wandering_monster_drawn)
    except RoomNotFoundError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message=str(e)) from e
    except InvalidTreasureSearchError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message=str(e)) from e

    return {
        "roomId": result.room_id,
        "spawnedMonster": result.spawned_monster,
        "monsterAttack": (
            {
                "monsterName": result.monster_attack.monster_name,
                "heroName": result.monster_attack.hero_name,
                "diceRolled": result.monster_attack.dice_rolled,
                "skulls": result.monster_attack.skulls,
            }
            if result.monster_attack
            else None
        ),
        "log": result.log,
    }


@firestore.transactional
def _apply_search_traps_and_secret_doors(transaction, db, game_ref, hero_id, room_id, search_type):
    game_state, quest = _load_game_and_quest(db, game_ref, transaction)

    if game_state.get("phase") != "hero":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="it is not the hero phase"
        )

    result = resolve_trap_search(
        board=_catalogs.board, quest=quest, game_state=game_state, hero_id=hero_id,
        room_id=room_id, search_type=search_type,
    )

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    new_log_entries = [{"turn": turn, "text": line} for line in result.log]
    searched_flag = "traps" if search_type == "traps" else "secretDoors"
    updates: dict = {f"searched.{room_id}.{searched_flag}": True, "log": existing_log + new_log_entries}

    if result.found_traps:
        # trapsFound, not trapsTriggered: the party now knows where these
        # are, but they are still armed (see engine/trap_search.py).
        traps_found = set(game_state.get("trapsFound", []))
        traps_found.update(t.trap_id for t in result.found_traps)
        updates["trapsFound"] = sorted(traps_found)

    for d in result.found_secret_doors:
        updates[f"doors.{d.door_id}"] = "closed"

    transaction.update(game_ref, updates)
    return result


@https_fn.on_call()
def search_traps_and_secret_doors(req: https_fn.CallableRequest) -> dict:
    """Searches the hero's current room, for EITHER traps or secret
    doors -- searchType picks one. The 1989 rulebook lists them as two
    distinct hero actions, and a hero takes one action per turn, so a
    single button doing both handed the party a free action. (The
    function keeps its original name so the deployed endpoint is not
    orphaned.) Fully digital: unlike treasure, traps and secret doors
    are quest-owned data the app already has, so this reveals whatever
    is actually there rather than drawing from a physical deck.
    Enforces one search of each kind per room. See
    functions/engine/trap_search.py for the pure
    resolution logic and its scoping notes (room traps + bordering
    secret doors only -- corridor traps and furniture traps are out of
    scope for this button).
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to play")

    data = req.data if isinstance(req.data, dict) else {}
    game_id = data.get("gameId")
    hero_id = data.get("heroId")
    room_id = data.get("roomId")
    # Defaults to "traps" so a client that predates the split still works.
    search_type = data.get("searchType", "traps")

    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")
    if not isinstance(hero_id, str) or not hero_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="heroId is required")
    if not isinstance(room_id, str) or not room_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="roomId is required")
    if search_type not in SEARCH_TYPES:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            message=f"searchType must be one of {sorted(SEARCH_TYPES)}",
        )

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    transaction = db.transaction()

    try:
        result = _apply_search_traps_and_secret_doors(transaction, db, game_ref, hero_id, room_id, search_type)
    except TrapSearchRoomNotFoundError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message=str(e)) from e
    except InvalidTrapSearchError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message=str(e)) from e

    return {
        "roomId": result.room_id,
        "foundTraps": [
            {"trapId": t.trap_id, "type": t.trap_type, "pos": list(t.pos), "placementInstruction": t.placement_instruction}
            for t in result.found_traps
        ],
        "foundSecretDoors": [
            {"doorId": d.door_id, "squares": [list(s) for s in d.squares], "placementInstruction": d.placement_instruction}
            for d in result.found_secret_doors
        ],
        "log": result.log,
    }


def _trap_lookup_entry(quest, trap_id):
    """(trap_type, pos) for a synthesized trap id, or None. Ids come from
    engine/hero_movement._build_trap_lookup, so they resolve the same way.
    """
    from engine.hero_movement import _build_trap_lookup

    for pos, (tid, ttype) in _build_trap_lookup(quest).items():
        if tid == trap_id:
            return ttype, pos
    return None


@firestore.transactional
def _apply_trap_action(transaction, db, game_ref, hero_id, trap_id, action, die_face, landing, has_tool_kit):
    game_state, quest = _load_game_and_quest(db, game_ref, transaction)

    if game_state.get("phase") != "hero":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="it is not the hero phase"
        )

    entry = _trap_lookup_entry(quest, trap_id)
    if entry is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message=f"no trap '{trap_id}' in this quest")
    trap_type, trap_pos = entry

    result = resolve_trap_action(
        board=_catalogs.board, quest=quest, game_state=game_state, hero_id=hero_id,
        trap_id=trap_id, trap_type=trap_type, trap_pos=trap_pos,
        action=action, die_face=die_face, landing=landing, has_tool_kit=has_tool_kit,
    )

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    heroes = game_state.get("heroes", [])
    for h in heroes:
        if h["id"] == hero_id:
            h["pos"] = list(result.hero_pos)

    new_log_entries = [{"turn": turn, "text": line} for line in result.log]
    updates: dict = {"heroes": to_firestore_coords(heroes)}

    if result.sprung:
        updates["trapsTriggered"] = sorted(set(game_state.get("trapsTriggered", [])) | {trap_id})
        if trap_type == "falling_block":
            collapsed = {tuple(sq) for sq in game_state.get("collapsedSquares", [])} | {tuple(trap_pos)}
            updates["collapsedSquares"] = to_firestore_coords(sorted(collapsed))
    if result.disarmed:
        # A disarmed trap is "gone" -- parking it in trapsTriggered is the
        # simplest way to make it permanently inert without a third registry.
        updates["trapsTriggered"] = sorted(set(game_state.get("trapsTriggered", [])) | {trap_id})

    # A jump (or a deliberate step) can land a hero on the stairway.
    _mark_objective_if_complete(quest, game_state, updates, new_log_entries, turn)
    updates["log"] = existing_log + new_log_entries

    transaction.update(game_ref, updates)
    return result


@https_fn.on_call()
def resolve_trap_action_endpoint(req: https_fn.CallableRequest) -> dict:
    """Jump, disarm, or deliberately step on a trap the party already
    found. Movement stops in front of a known trap, so this is the
    follow-up action -- same two-step shape as open_door.

    The die is the HERO's: the app names the roll, the player reports
    the face ("skull" | "white_shield" | "black_shield"), and the engine
    applies the consequence. hasToolKit is asserted by the caller
    because inventory is physical (the Dwarf needs no kit).
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to play")

    data = req.data if isinstance(req.data, dict) else {}
    game_id = data.get("gameId")
    hero_id = data.get("heroId")
    trap_id = data.get("trapId")
    action = data.get("action")
    die_face = data.get("dieFace")
    landing = data.get("landing")
    has_tool_kit = bool(data.get("hasToolKit", False))

    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")
    if not isinstance(hero_id, str) or not hero_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="heroId is required")
    if not isinstance(trap_id, str) or not trap_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="trapId is required")
    if action not in TRAP_ACTIONS:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message=f"action must be one of {sorted(TRAP_ACTIONS)}"
        )
    if landing is not None:
        landing = tuple(from_firestore_coords(landing))

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    transaction = db.transaction()

    try:
        result = _apply_trap_action(
            transaction, db, game_ref, hero_id, trap_id, action, die_face, landing, has_tool_kit
        )
    except InvalidTrapActionError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message=str(e)) from e

    return {
        "trapId": result.trap_id,
        "action": result.action,
        "sprung": result.sprung,
        "disarmed": result.disarmed,
        "heroPos": list(result.hero_pos),
        "placementInstruction": result.placement_instruction,
        "log": result.log,
    }


@firestore.transactional
def _apply_cast_spell(transaction, db, game_ref, hero_id, spell_name, target_monster_id, skulls, monster_defends):
    game_state, quest = _load_game_and_quest(db, game_ref, transaction)

    if game_state.get("phase") != "hero":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="it is not the hero phase"
        )

    result = resolve_hero_spell(
        board=_catalogs.board, catalogs=_catalogs, quest=quest, game_state=game_state,
        hero_id=hero_id, spell_name=spell_name, target_monster_id=target_monster_id,
        skulls=skulls, monster_defends=monster_defends,
    )

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    new_log_entries = [{"turn": turn, "text": line} for line in result.log]

    updates: dict = {"spellsCast": sorted(set(game_state.get("spellsCast", [])) | {result.spell_name})}

    if result.defense is not None and target_monster_id:
        monster = game_state["monsters"][target_monster_id]
        monster["currentBody"] = result.defense.body_points_after
        updates[f"monsters.{target_monster_id}.currentBody"] = result.defense.body_points_after
        if result.defense.defeated:
            monster["alive"] = False
            updates[f"monsters.{target_monster_id}.alive"] = False

    _mark_objective_if_complete(quest, game_state, updates, new_log_entries, turn)
    updates["log"] = existing_log + new_log_entries

    transaction.update(game_ref, updates)
    return result


@https_fn.on_call()
def cast_spell(req: https_fn.CallableRequest) -> dict:
    """The Elf or Wizard casts a spell instead of attacking.

    Spell cards are physical, so the app never learns what a spell
    does: the player names the card, and for an attack spell reports
    the skulls it rolled, exactly as with a weapon attack. What the app
    enforces is the rulebook's frame -- caster class, line of sight to
    the target, and one cast per spell per quest. See
    functions/engine/spell.py.
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to play")

    data = req.data if isinstance(req.data, dict) else {}
    game_id = data.get("gameId")
    hero_id = data.get("heroId")
    spell_name = data.get("spellName")
    target_monster_id = data.get("targetMonsterId")
    skulls = data.get("skulls", 0)
    monster_defends = data.get("monsterDefends", True)

    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")
    if not isinstance(hero_id, str) or not hero_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="heroId is required")
    if not isinstance(spell_name, str) or not spell_name.strip():
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="spellName is required")
    if target_monster_id is not None and not isinstance(target_monster_id, str):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="targetMonsterId must be a string"
        )
    if not isinstance(skulls, int) or isinstance(skulls, bool) or skulls < 0:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="skulls must be a non-negative integer"
        )

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    transaction = db.transaction()

    try:
        result = _apply_cast_spell(
            transaction, db, game_ref, hero_id, spell_name, target_monster_id, skulls, bool(monster_defends)
        )
    except InvalidSpellError as e:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message=str(e)) from e

    return {
        "heroId": result.hero_id,
        "spellName": result.spell_name,
        "targetMonsterId": result.target_monster_id,
        "defeated": result.defense.defeated if result.defense else False,
        "bodyPointsAfter": result.defense.body_points_after if result.defense else None,
        "log": result.log,
    }


VALID_TURN_TYPES = {"normal", "cunning", "wandering"}


@https_fn.on_call()
def roll_zargon_turn_type(req: https_fn.CallableRequest) -> dict:
    """Rolls Zargon's turn type (the digital Zargon Deck) for a game.
    Read-only -- does not touch game state. Split from resolve_zargon_turn
    because a cunning roll sometimes needs a human answer ("which hero
    is lowest on BP?") before it can be resolved, and that answer can't
    be collected inside one atomic call. The client pins the rolled
    type and passes it to resolve_zargon_turn rather than this function
    re-rolling it, which could silently change the outcome between
    asking and answering.
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to play")

    data = req.data if isinstance(req.data, dict) else {}
    game_id = data.get("gameId")
    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    game_state, quest = _load_game_and_quest(db, game_ref)

    generation_params = quest.get("generationParams", {})
    hero_count = generation_params.get("heroCount")
    difficulty = generation_params.get("difficulty", "standard")
    if hero_count not in (1, 2, 3, 4):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="quest has no valid heroCount"
        )

    turn_type = roll_turn_type(hero_count, difficulty)
    heroes = game_state.get("heroes", [])
    needs_prompt = turn_type == "cunning" and needs_cunning_target_prompt(heroes)

    return {
        "turnType": turn_type,
        "needsCunningPrompt": needs_prompt,
        "heroes": [{"id": h["id"], "name": h.get("name", h["id"])} for h in heroes] if needs_prompt else [],
    }


@firestore.transactional
def _apply_zargon_turn(transaction, db, game_ref, turn_type, lowest_bp_hero_id):
    game_state, quest = _load_game_and_quest(db, game_ref, transaction)

    if game_state.get("phase") != "zargon":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="it is not Zargon's phase"
        )

    result = resolve_zargon_turn_engine(
        board=_catalogs.board,
        catalogs=_catalogs,
        quest=quest,
        game_state=game_state,
        turn_type=turn_type,
        lowest_bp_hero_id=lowest_bp_hero_id,
    )

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    new_log_entries = [{"turn": turn, "text": line} for line in result.log]
    # Stamped with the NEW turn number so the log reads as a clean
    # boundary instead of trailing off the end of Zargon's turn.
    new_log_entries.append({"turn": turn + 1, "text": f"--- Turn {turn + 1} ---"})
    updates: dict = {"log": existing_log + new_log_entries, "phase": "hero", "turn": turn + 1, "heroPhaseSegment": 1}

    for monster_id, new_pos in result.updated_monster_positions.items():
        updates[f"monsters.{monster_id}.pos"] = to_firestore_coords(list(new_pos))

    if result.spawned_monster:
        existing_ids = set(game_state.get("monsters", {}).keys())
        new_monster_id = _next_wandering_monster_id(existing_ids)
        spawn = result.spawned_monster
        catalog_entry = _catalogs.monsters.get(spawn["type"], {})
        updates[f"monsters.{new_monster_id}"] = to_firestore_coords(
            {
                "type": spawn["type"],
                "pos": list(spawn["pos"]),
                "currentBody": catalog_entry.get("body", 1),
                "alive": True,
            }
        )

    transaction.update(game_ref, updates)
    return result


@https_fn.on_call()
def resolve_zargon_turn(req: https_fn.CallableRequest) -> dict:
    """Resolves Zargon's turn given an ALREADY-ROLLED turn type from
    roll_zargon_turn_type. Advances every active monster (movement +
    attack, or a guard's hold/engage decision on a cunning turn), or
    spawns a fresh wandering monster at the frontier nearest the party.
    Hands the phase back to "hero" and advances the turn counter. See
    functions/engine/zargon_turn.py for the pure resolution logic.
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to play")

    data = req.data if isinstance(req.data, dict) else {}
    game_id = data.get("gameId")
    turn_type = data.get("turnType")
    lowest_bp_hero_id = data.get("lowestBpHeroId")

    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")
    if turn_type not in VALID_TURN_TYPES:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message=f"turnType must be one of {sorted(VALID_TURN_TYPES)}"
        )

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    transaction = db.transaction()

    try:
        result = _apply_zargon_turn(transaction, db, game_ref, turn_type, lowest_bp_hero_id)
    except ValueError as e:
        # select_cunning_target raises this for a missing/invalid answer
        # -- a client that skipped roll_zargon_turn_type's prompt signal.
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message=str(e)) from e

    return {
        "turnType": result.turn_type,
        "monsterResults": [
            {
                "monsterId": mr.monster_id,
                "monsterName": mr.monster_name,
                "action": mr.action,
                "endPos": list(mr.turn_result.end_pos) if mr.turn_result else None,
                "attackedHeroName": mr.turn_result.attack.hero_name if mr.turn_result and mr.turn_result.attack else None,
                "skulls": mr.turn_result.attack.skulls if mr.turn_result and mr.turn_result.attack else None,
            }
            for mr in result.monster_results
        ],
        "spawnedMonster": result.spawned_monster,
        "log": result.log,
    }


@firestore.transactional
def _apply_hero_attack(transaction, db, game_ref, monster_id, skulls):
    game_state, quest = _load_game_and_quest(db, game_ref, transaction)

    if game_state.get("phase") != "hero":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message="it is not the hero phase"
        )

    monster_def = _monster_defs(quest).get(monster_id)
    if monster_def is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message=f"monster '{monster_id}' not found in quest")

    monster_state = game_state.get("monsters", {}).get(monster_id)
    if monster_state is None or not monster_state.get("alive"):
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message=f"monster '{monster_id}' is not alive"
        )

    catalog_entry = _catalogs.monsters.get(monster_def["type"])
    if catalog_entry is None:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.FAILED_PRECONDITION, message=f"unknown monster type '{monster_def['type']}'"
        )
    overrides = monster_def.get("overrides", {})
    defend_dice = overrides.get("defend", catalog_entry["defend"])
    monster_name = monster_def.get("name") or monster_def["type"]

    result = resolve_hero_attack_engine(
        monster_name=monster_name,
        monster_defend_dice=defend_dice,
        skulls=skulls,
        current_body=monster_state["currentBody"],
    )

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    new_log_entries = [{"turn": turn, "text": result.log}]

    game_state["monsters"][monster_id]["alive"] = not result.defeated
    updates = {
        f"monsters.{monster_id}.currentBody": result.body_points_after,
        f"monsters.{monster_id}.alive": not result.defeated,
    }
    _mark_objective_if_complete(quest, game_state, updates, new_log_entries, turn)
    updates["log"] = existing_log + new_log_entries

    transaction.update(game_ref, updates)

    return result


@https_fn.on_call()
def resolve_hero_attack(req: https_fn.CallableRequest) -> dict:
    """A hero has rolled their own attack dice physically and reports
    the skull count via the "attack [target]" button. Rolls the
    monster's defend dice digitally (Zargon's dice) and applies the
    resulting damage -- the only direction combat touches stored state,
    per CLAUDE.md's "app applies results to monsters only".
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to play")

    data = req.data if isinstance(req.data, dict) else {}
    game_id = data.get("gameId")
    monster_id = data.get("monsterId")
    skulls = data.get("skulls")

    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")
    if not isinstance(monster_id, str) or not monster_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="monsterId is required")
    if not isinstance(skulls, int) or isinstance(skulls, bool) or skulls < 0:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="skulls must be a non-negative integer"
        )

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    transaction = db.transaction()

    result = _apply_hero_attack(transaction, db, game_ref, monster_id, skulls)

    return {
        "monsterName": result.monster_name,
        "diceRolled": result.dice_rolled,
        "blocks": result.blocks,
        "skullsFaced": result.skulls_faced,
        "damage": result.damage,
        "bodyPointsBefore": result.body_points_before,
        "bodyPointsAfter": result.body_points_after,
        "defeated": result.defeated,
        "log": result.log,
    }


@firestore.transactional
def _apply_record_hero_defense(transaction, game_ref, hero_id, skulls_faced, shields_reported):
    game_state = _load_game(game_ref, transaction)

    hero = next((h for h in game_state.get("heroes", []) if h["id"] == hero_id), None)
    if hero is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.NOT_FOUND, message=f"hero '{hero_id}' not found in game")

    log_line = record_hero_defense_engine(
        hero_name=hero.get("name", hero_id), skulls_faced=skulls_faced, shields_reported=shields_reported
    )

    turn = game_state.get("turn", 0)
    existing_log = game_state.get("log", [])
    transaction.update(game_ref, {"log": existing_log + [{"turn": turn, "text": log_line}]})

    return log_line


@https_fn.on_call()
def record_hero_defense(req: https_fn.CallableRequest) -> dict:
    """A monster's attack (from resolve_zargon_turn) named this hero as
    its target. The hero defends with their own physical dice and
    reports shields via this button purely to complete the turn log's
    narration -- see engine/combat.py's record_hero_defense: it never
    computes or stores hero body points, that stays on the physical
    hero sheet. skullsFaced is the skull count already returned by
    resolve_zargon_turn's monsterResults for this hero, echoed back by
    the client rather than re-derived here.
    """
    if req.auth is None:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="sign in to play")

    data = req.data if isinstance(req.data, dict) else {}
    game_id = data.get("gameId")
    hero_id = data.get("heroId")
    skulls_faced = data.get("skullsFaced")
    shields_reported = data.get("shieldsReported")

    if not isinstance(game_id, str) or not game_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="gameId is required")
    if not isinstance(hero_id, str) or not hero_id:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="heroId is required")
    if not isinstance(skulls_faced, int) or isinstance(skulls_faced, bool) or skulls_faced < 0:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="skullsFaced must be a non-negative integer"
        )
    if not isinstance(shields_reported, int) or isinstance(shields_reported, bool) or shields_reported < 0:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="shieldsReported must be a non-negative integer"
        )

    db = firestore.client()
    game_ref = db.collection("games").document(game_id)
    transaction = db.transaction()

    log_line = _apply_record_hero_defense(transaction, game_ref, hero_id, skulls_faced, shields_reported)

    return {"log": log_line}
