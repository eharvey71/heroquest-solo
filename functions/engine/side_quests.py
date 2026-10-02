"""Side quests: short narrative scenes played on their own page, written
by the model together with the quest, resolved here one passage at a
time. design/side-quests-design.md is the contract; this module is the
rules half of it.

The model wrote the prose and the choice graph. It never decides an
outcome: every choice resolves to an effect from EFFECT_POINTS (a
closed list), and this module applies them. Dice keep the app's usual
terms -- a hero's combat dice are rolled at the table and the skull
count reported; a Mind or Body test is reported as pass/fail so the app
never learns the value; Zargon's own tests are rolled here.

Game state a scene touches:
- game.sideQuests[id] = {status, passageId, flags, history, retried}
  -- absent until begun. status is "active" or a terminal outcome.
- game.pendingSideQuest = id while a scene is in progress. It locks the
  main game exactly the way pendingTreasureDraw does.
- game.gate = {kind, sideQuestId, target..., state} -- the required
  scene's hold on the OBJECTIVE (never a door): "ward" makes the boss
  immune to hero damage, "seal" stops the objective completing. state
  is closed | open | cracked; a required scene that ends can never
  leave it closed (fail forward -- see crack_gate below).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from validator.catalogs import Board, Catalogs

from .dice import roll_attack
from .hero_movement import _build_trap_lookup
from .hero_spells import HERO_SPELLS, spellbook_for
from .hero_status import add_status as add_hero_status
from .heroes import living_heroes
from .movement import revealed_squares
from .names import monster_display_name
from .targeting import spawn_wandering_monster_from_turn_roll

Coord = tuple[int, int]

KINDS = ("optional", "required")
SETTINGS = ("town", "forest", "cave", "shrine", "road", "vision")
HOOK_WHENS = ("prologue", "room")
TEST_KINDS = ("combat_dice", "mind", "body", "zargon")
OUTCOMES = ("success", "partial", "failure")
GATE_KINDS = ("ward", "seal")
HERO_IDS = ("barbarian", "dwarf", "elf", "wizard")
ELEMENTS = ("Air", "Earth", "Fire", "Water")
REWARD_KINDS = ("gold", "potion", "equipment", "body")
COST_KINDS = ("body", "gold")

# Boon points per effect -- what the validator caps a terminal's total
# at (design section 6). remove_monster is priced from the monster's
# threat at validation time and is 0 here only as a placeholder.
EFFECT_POINTS = {
    "break_gate": 0,
    "crack_gate": 0,
    "grant_artifact": 3,
    "weaken_monster": 2,
    "remove_monster": 0,
    "reveal_traps": 1,
    "reveal_secret_doors": 1,
    "spawn_wandering": -1,
    "miss_turn": -1,
    "announce_reward": 0,  # by kind, see REWARD_POINTS
    "announce_cost": -1,
    "armory_visit": 0,
}
REWARD_POINTS = {"gold": 1, "potion": 2, "equipment": 2, "body": 1}
EFFECT_TYPES = tuple(EFFECT_POINTS)

# The town beat (design section 9). The 1989 book opens the Armory
# between quests; a town scene is the one time the party is standing
# in front of it mid-quest.
ARMORY_REMINDER = (
    "You are in town, and the Armory is open. Normally a between-quests visit -- but you are "
    "here now. Use the physical Armory card and your own gold; the app tracks neither. "
    "(House rule: buying mid-quest. Skip it if you'd rather keep to the book.)"
)
ARMORY_BETWEEN_QUESTS = (
    "Between quests the Armory is open: spend the gold this quest earned on weapons and armor "
    "before the next one (1989 rulebook, What Happens Between Quests)."
)


class SideQuestError(ValueError):
    """The action can't happen: no such scene, not available from where
    the party stands, a choice that isn't on offer, a missing die
    report."""


@dataclass
class SideQuestStep:
    updates: dict
    log: list[str] = field(default_factory=list)
    placements: list[str] = field(default_factory=list)
    finished: bool = False
    outcome: str | None = None
    passage_id: str | None = None


# ---- lookups ---------------------------------------------------------------


def side_quest_by_id(quest: dict, sq_id: str) -> dict | None:
    return next((sq for sq in quest.get("sideQuests", []) or [] if sq.get("id") == sq_id), None)


def is_terminal(sq: dict, node_id: str) -> bool:
    return node_id in (sq.get("terminals") or {})


def _hero_squares_in_room(board: Board, game_state: dict, room_id: str) -> list[dict]:
    squares = set(board.room_squares.get(room_id, ()))
    return [h for h in living_heroes(game_state) if tuple(h["pos"]) in squares]


def hook_available(board: Board, game_state: dict, sq: dict) -> bool:
    """Can the party begin this scene from where it stands? A prologue
    is always on offer; a room hook needs the room revealed and a
    living hero inside it. Stays available on a return visit (owner's
    call, design section 15)."""
    hook = sq.get("hook") or {}
    if hook.get("when") == "prologue":
        return True
    room = hook.get("room")
    if not room or room not in game_state.get("revealed", {}).get("rooms", []):
        return False
    return bool(_hero_squares_in_room(board, game_state, room))


def element_unspent(game_state: dict, element: str) -> bool:
    """Does some living caster hold this element with at least one card
    of it still unspent? spellbooks and spellsCast are digital, so this
    is exact -- the one requirement tag the app can check itself."""
    spent = set(game_state.get("spellsCast", []))
    for hero in living_heroes(game_state):
        for spell_id in spellbook_for(game_state, hero["id"]):
            if HERO_SPELLS[spell_id]["element"].lower() == element.lower() and spell_id not in spent:
                return True
    return False


def choice_visible(choice: dict, game_state: dict, progress: dict, sq: dict) -> bool:
    """The client filters the same way; the server is the one that
    counts. A retry edge is offered once."""
    hero = choice.get("requiresHero")
    if hero and not any(h["id"] == hero for h in living_heroes(game_state)):
        return False
    element = choice.get("requiresElement")
    if element and not element_unspent(game_state, element):
        return False
    flag = choice.get("requiresFlag")
    if flag and flag not in (progress.get("flags") or []):
        return False
    retry = sq.get("retry")
    if retry and progress.get("retried") and _is_retry_edge(sq, progress.get("passageId"), _choice_targets(choice)):
        return False
    return True


def _choice_targets(choice: dict) -> set[str]:
    test = choice.get("test") or {}
    if test.get("kind") and test.get("kind") != "none":
        return {test.get("success"), test.get("failure")} - {None, ""}
    return {choice.get("next")} - {None, ""}


def _is_retry_edge(sq: dict, from_id: str | None, targets: set[str]) -> bool:
    retry = sq.get("retry") or {}
    return bool(retry) and from_id == retry.get("from") and retry.get("to") in targets


# ---- discovery ---------------------------------------------------------------
#
# The Journal must never say where a scene is before the party has found
# it (owner's call, after the first live game: entries naming "R13"
# appeared as soon as a door opened). So discovery is physical: when a
# room with an NPC hook is REVEALED the player is told to place a
# figure -- what opening a door shows in the physical game -- and only
# when a hero is standing IN the room does the scene become "known"
# and the Journal show its name, place and offer. Both are recorded by
# the endpoints that move heroes and open doors, via these two helpers.


def npc_placements(quest: dict, game_state: dict, rooms) -> list[str]:
    """Placement lines for every room-hooked scene whose room is among
    `rooms` (just revealed). Expanded games only. Says WHO stands there
    and what figure to use -- nothing about the scene."""
    if game_state.get("mode") != "expanded":
        return []
    lines = []
    for sq in quest.get("sideQuests", []) or []:
        hook = sq.get("hook") or {}
        if hook.get("when") != "room" or hook.get("room") not in set(rooms):
            continue
        who = hook.get("npcName") or "something that wants your attention"
        figure = hook.get("figureHint") or "any spare figure"
        lines.append(f"Place a figure for {who} anywhere in {hook['room']} ({figure}).")
    return lines


def encounter_updates(board: Board, quest: dict, game_state: dict) -> tuple[dict, list[str]]:
    """Marks every not-yet-begun room-hooked scene whose room now holds a
    living hero as "known" (game.sideQuests[id] = {status: "known"}),
    mutating game_state, and returns (Firestore updates, log lines).
    Idempotent. The scene's offer -- the hook text -- is logged once,
    here, when the party first meets it."""
    if game_state.get("mode") != "expanded":
        return {}, []
    updates: dict = {}
    log: list[str] = []
    progress_all = game_state.setdefault("sideQuests", {})
    for sq in quest.get("sideQuests", []) or []:
        hook = sq.get("hook") or {}
        if hook.get("when") != "room" or sq.get("id") in progress_all:
            continue
        if not _hero_squares_in_room(board, game_state, hook.get("room", "")):
            continue
        progress_all[sq["id"]] = {"status": "known"}
        updates[f"sideQuests.{sq['id']}"] = {"status": "known"}
        who = hook.get("npcName") or "Someone here"
        log.append(f"[{sq.get('title', sq['id'])}] {who}: {hook.get('text', '').strip()} (See the Journal.)".strip())
    return updates, log


# ---- the gate --------------------------------------------------------------


def ward_blocks(game_state: dict, monster_id: str) -> bool:
    gate = game_state.get("gate") or {}
    return gate.get("kind") == "ward" and gate.get("state") == "closed" and gate.get("targetMonsterId") == monster_id


def seal_blocks(game_state: dict) -> bool:
    gate = game_state.get("gate") or {}
    return gate.get("kind") == "seal" and gate.get("state") == "closed"


def notice_gate(game_state: dict) -> dict:
    """First time the party runs into the gate: marks it noticed (the
    Journal lists the required scene as a rumour from then on, not
    before) and returns the Firestore update, or {} if already noticed."""
    gate = game_state.get("gate") or {}
    if not gate or gate.get("noticed"):
        return {}
    gate["noticed"] = True
    return {"gate.noticed": True}


def gate_notice(quest: dict, game_state: dict) -> str:
    """The log line for a blow turned aside or a goal still sealed. Names
    the scene only once the party has met it; before that it would hand
    them a title they haven't found."""
    gate = game_state.get("gate") or {}
    sq_id = gate.get("sideQuestId", "")
    sq = side_quest_by_id(quest, sq_id)
    met = sq_id in (game_state.get("sideQuests") or {})
    where = f"(Journal: {sq.get('title', sq_id)})" if sq and met else "(See the Journal.)"
    reason = gate.get("text") or ""
    if gate.get("kind") == "ward":
        return f"The blow turns aside -- {gate.get('targetName', 'the foe')} is warded. {reason} {where}".strip()
    return f"It cannot be finished yet -- the way is sealed. {reason} {where}".strip()


# ---- begin / advance -------------------------------------------------------


def begin_side_quest(*, board: Board, quest: dict, game_state: dict, sq_id: str) -> SideQuestStep:
    if game_state.get("mode") != "expanded":
        raise SideQuestError("this game is being played the traditional way -- no side quests")
    if game_state.get("pendingSideQuest"):
        raise SideQuestError("a side quest is already in progress")
    sq = side_quest_by_id(quest, sq_id)
    if sq is None:
        raise SideQuestError(f"no side quest '{sq_id}' in this quest")
    progress = (game_state.get("sideQuests") or {}).get(sq_id)
    if progress and progress.get("status") not in (None, "known", "active"):
        raise SideQuestError(f"'{sq.get('title', sq_id)}' is already over")
    if not hook_available(board, game_state, sq):
        raise SideQuestError(f"a hero must be standing in the room where '{sq.get('title', sq_id)}' is offered")

    if not progress or progress.get("status") == "known":
        # "known" is the encounter record (encounter_updates): the party
        # has met the hook but not begun the scene. Begin starts fresh.
        progress = {"status": "active", "passageId": sq["start"], "flags": [], "history": [], "retried": False}
    game_state.setdefault("sideQuests", {})[sq_id] = progress
    game_state["pendingSideQuest"] = sq_id
    hook_text = (sq.get("hook") or {}).get("text") or ""
    return SideQuestStep(
        updates={f"sideQuests.{sq_id}": progress, "pendingSideQuest": sq_id},
        log=[f"[{sq.get('title', sq_id)}] {hook_text}".strip()],
        passage_id=progress["passageId"],
    )


def advance_side_quest(
    *,
    board: Board,
    catalogs: Catalogs,
    quest: dict,
    game_state: dict,
    choice_id: str,
    report: dict | None = None,
    rng: random.Random | None = None,
) -> SideQuestStep:
    sq_id = game_state.get("pendingSideQuest")
    if not sq_id:
        raise SideQuestError("no side quest is in progress")
    sq = side_quest_by_id(quest, sq_id)
    progress = (game_state.get("sideQuests") or {}).get(sq_id)
    if sq is None or not progress or progress.get("status") != "active":
        raise SideQuestError("the side quest in progress can't be found")
    title = sq.get("title", sq_id)
    passage = (sq.get("passages") or {}).get(progress.get("passageId"))
    if passage is None:
        raise SideQuestError("the scene has lost its place")
    choice = next((c for c in passage.get("choices", []) if c.get("id") == choice_id), None)
    if choice is None or not choice_visible(choice, game_state, progress, sq):
        raise SideQuestError("that choice isn't on offer")

    rng = rng or random.Random()
    log: list[str] = [f"[{title}] {choice.get('label', '')}".strip()]
    test = choice.get("test") or {}
    kind = test.get("kind") if test.get("kind") != "none" else None
    if kind:
        passed, line = _resolve_test(kind, test, report, rng)
        log.append(f"[{title}] {line}")
        next_id = test.get("success") if passed else test.get("failure")
    else:
        next_id = choice.get("next")
    if not next_id:
        raise SideQuestError("that choice leads nowhere")

    flag = choice.get("setsFlag")
    if flag and flag not in progress.setdefault("flags", []):
        progress["flags"].append(flag)
    progress.setdefault("history", []).append(choice_id)

    placements: list[str] = []
    updates: dict = {}
    if _is_retry_edge(sq, progress.get("passageId"), {next_id}):
        progress["retried"] = True
        cost = (sq.get("retry") or {}).get("costText")
        if cost:
            log.append(f"[{title}] {cost} (apply it to the hero sheet)")

    progress["passageId"] = next_id
    finished = is_terminal(sq, next_id)
    outcome = None
    if finished:
        terminal = sq["terminals"][next_id]
        outcome = terminal.get("outcome", "failure")
        progress["status"] = outcome
        if terminal.get("text"):
            log.append(f"[{title}] {terminal['text']}")
        effects = list(terminal.get("effects") or [])
        # Fail forward: a required scene that ends can never leave its
        # gate closed, whatever the model wrote on this terminal.
        gate = game_state.get("gate") or {}
        if sq.get("kind") == "required" and gate.get("sideQuestId") == sq_id and gate.get("state") == "closed":
            types = {e.get("type") for e in effects}
            if outcome == "success" and "break_gate" not in types:
                effects.append({"type": "break_gate"})
            elif outcome != "success" and not ({"break_gate", "crack_gate"} & types):
                effects.append({"type": "crack_gate"})
        eff_updates, eff_log, eff_placements = apply_effects(
            board=board, catalogs=catalogs, quest=quest, game_state=game_state, effects=effects, sq=sq, rng=rng
        )
        updates.update(eff_updates)
        log.extend(eff_log)
        placements.extend(eff_placements)
        game_state["pendingSideQuest"] = None
        updates["pendingSideQuest"] = None
        log.append(f"[{title}] The scene ends -- {_outcome_word(outcome)}. The party returns to the dungeon.")

    updates[f"sideQuests.{sq_id}"] = progress
    return SideQuestStep(
        updates=updates, log=log, placements=placements, finished=finished, outcome=outcome, passage_id=next_id
    )


def _outcome_word(outcome: str) -> str:
    return {"success": "a success", "partial": "a partial success", "failure": "a failure"}.get(outcome, outcome)


def _resolve_test(kind: str, test: dict, report: dict | None, rng: random.Random) -> tuple[bool, str]:
    report = report or {}
    need = int(test.get("needSkulls") or 1)
    dice = int(test.get("dice") or 1)
    if kind == "combat_dice":
        skulls = report.get("skulls")
        if not isinstance(skulls, int) or not 0 <= skulls <= dice:
            raise SideQuestError(f"report the skulls rolled on {dice} combat dice (0-{dice})")
        passed = skulls >= need
        return passed, f"{skulls} skull(s) on {dice} combat dice, {need} needed -- {'success' if passed else 'failure'}."
    if kind in ("mind", "body"):
        passed = report.get("passed")
        if not isinstance(passed, bool):
            raise SideQuestError(f"report whether the {kind.title()} Point roll succeeded")
        return passed, f"{kind.title()} Point test -- {'passed' if passed else 'failed'}."
    if kind == "zargon":
        skulls = roll_attack(dice, rng)
        passed = skulls >= need
        return passed, f"Zargon rolls {dice} combat dice: {skulls} skull(s), {need} needed -- {'success' if passed else 'failure'}."
    raise SideQuestError(f"unknown test '{kind}'")


# ---- effects ---------------------------------------------------------------


def _next_wandering_id(existing_ids) -> str:
    i = 1
    while f"W{i}" in existing_ids:
        i += 1
    return f"W{i}"


def _monster_name(quest: dict, monster_id: str) -> str:
    for room in quest.get("rooms", {}).values():
        for m in room.get("monsters", []):
            if m.get("id") == monster_id:
                return m.get("name") or monster_display_name(m.get("type", monster_id))
    return monster_id


def _hero_for(game_state: dict, hero_id: str | None) -> dict | None:
    heroes = living_heroes(game_state)
    if hero_id:
        hero = next((h for h in heroes if h["id"] == hero_id), None)
        if hero is not None:
            return hero
    return heroes[0] if heroes else None


def apply_effects(
    *,
    board: Board,
    catalogs: Catalogs,
    quest: dict,
    game_state: dict,
    effects: list[dict],
    sq: dict,
    rng: random.Random | None = None,
) -> tuple[dict, list[str], list[str]]:
    """Applies a terminal's effects to `game_state` in place and returns
    (Firestore updates, log lines, placement instructions). Anything the
    app owns is changed; anything on the hero sheet is announced."""
    rng = rng or random.Random()
    title = sq.get("title", "Side quest")
    updates: dict = {}
    log: list[str] = []
    placements: list[str] = []
    turn = game_state.get("turn", 0)
    gate = game_state.get("gate") or {}

    def say(text: str) -> None:
        log.append(f"[{title}] {text}")

    for effect in effects:
        etype = effect.get("type")

        if etype == "break_gate":
            if gate:
                gate["state"] = "open"
                updates["gate.state"] = "open"
                say(
                    f"The ward on {gate.get('targetName', 'the foe')} is broken -- they can be harmed now."
                    if gate.get("kind") == "ward"
                    else "The seal is undone -- the way to the quest's end is open."
                )

        elif etype == "crack_gate":
            if gate and gate.get("state") == "closed":
                gate["state"] = "cracked"
                updates["gate.state"] = "cracked"
                if gate.get("kind") == "ward":
                    mid = gate.get("targetMonsterId")
                    monster = game_state.get("monsters", {}).get(mid)
                    if monster is not None:
                        monster["currentBody"] = int(monster.get("currentBody", 1)) + 1
                        monster["bonusDefend"] = int(monster.get("bonusDefend", 0)) + 1
                        updates[f"monsters.{mid}.currentBody"] = monster["currentBody"]
                        updates[f"monsters.{mid}.bonusDefend"] = monster["bonusDefend"]
                    say(
                        f"The ward cracks but does not break: {gate.get('targetName', 'the foe')} can be harmed, "
                        f"yet fights on with one more defend die and one more Body Point."
                    )
                else:
                    say(
                        "The seal cracks but does not lift: the quest can still be finished, "
                        "but forcing it costs every hero 1 Body Point (apply it to the sheets)."
                    )
                    _spawn(board, catalogs, quest, game_state, updates, placements, say, why="Something heard the seal break")

        elif etype == "grant_artifact":
            artifact_id = effect.get("artifactId")
            card = catalogs.artifacts.get(artifact_id) if artifact_id else None
            hero = _hero_for(game_state, effect.get("heroId"))
            if card and hero:
                game_state.setdefault("artifactsHeld", {})[artifact_id] = hero["id"]
                updates[f"artifactsHeld.{artifact_id}"] = hero["id"]
                say(f"{hero.get('name', hero['id'])} takes the {card.get('name', artifact_id)} -- hand over the Artifact card. {card.get('text', '')}".strip())

        elif etype == "weaken_monster":
            mid = effect.get("monsterId")
            monster = game_state.get("monsters", {}).get(mid)
            if monster is not None and monster.get("alive", True):
                name = _monster_name(quest, mid)
                if effect.get("stat") == "defend":
                    monster["bonusDefend"] = int(monster.get("bonusDefend", 0)) - 1
                    updates[f"monsters.{mid}.bonusDefend"] = monster["bonusDefend"]
                    say(f"{name} will defend with one die fewer.")
                else:
                    monster["currentBody"] = max(1, int(monster.get("currentBody", 1)) - 1)
                    updates[f"monsters.{mid}.currentBody"] = monster["currentBody"]
                    say(f"{name} is weakened -- one Body Point fewer.")

        elif etype == "remove_monster":
            mid = effect.get("monsterId")
            monster = game_state.get("monsters", {}).get(mid)
            if monster is not None and monster.get("alive", True):
                monster["alive"] = False
                updates[f"monsters.{mid}.alive"] = False
                say(f"{_monster_name(quest, mid)} will not be there when you arrive.")

        elif etype == "reveal_traps":
            room = effect.get("room")
            lookup = _build_trap_lookup(quest)
            found = game_state.get("trapsFound") or {}
            traps_found = dict(found) if isinstance(found, dict) else {t: {} for t in found}
            count = 0
            for pos, (tid, ttype) in lookup.items():
                if tid.startswith(f"{room}-") and tid not in set(game_state.get("trapsTriggered", [])):
                    traps_found[tid] = {"type": ttype, "pos": list(pos)}
                    count += 1
            game_state["trapsFound"] = traps_found
            updates["trapsFound"] = traps_found
            game_state.setdefault("searched", {}).setdefault(room, {})["traps"] = True
            updates[f"searched.{room}.traps"] = True
            say(
                f"You learn where the traps lie in the room ahead -- {count} marked on the map."
                if count
                else "You learn the room ahead holds no traps."
            )

        elif etype == "reveal_secret_doors":
            room = effect.get("room")
            room_squares = set(board.room_squares.get(room, ()))
            doors = game_state.setdefault("doors", {})
            count = 0
            for door in quest.get("doors", []):
                squares = [tuple(sq_) for sq_ in door.get("squares", [])]
                if door.get("state") != "secret" or not any(sq_ in room_squares for sq_ in squares):
                    continue
                if doors.get(door["id"]) in ("closed", "open"):
                    continue
                doors[door["id"]] = "closed"
                updates[f"doors.{door['id']}"] = "closed"
                a, b = squares
                placements.append(f"Place a secret door tile on the wall between [{a[0]},{a[1]}] and [{b[0]},{b[1]}].")
                count += 1
            say(
                f"A hidden way is shown to you -- {count} secret door(s) marked on the map."
                if count
                else "There are no hidden ways in the room you were told of."
            )

        elif etype == "spawn_wandering":
            _spawn(board, catalogs, quest, game_state, updates, placements, say, why="Something has picked up your trail")

        elif etype == "miss_turn":
            hero = _hero_for(game_state, effect.get("heroId"))
            if hero is not None:
                add_hero_status(game_state, hero["id"], status="dazed", spell=title, turn=turn, misses_turns=1)
                updates["heroStatus"] = game_state.get("heroStatus", {})
                say(f"{hero.get('name', hero['id'])} is left reeling and misses a turn.")

        elif etype == "announce_reward":
            say(f"{effect.get('text', '').strip()} (apply it to the hero sheet)")

        elif etype == "announce_cost":
            say(f"{effect.get('text', '').strip()} (apply it to the hero sheet)")

        elif etype == "armory_visit":
            say(ARMORY_REMINDER)

    return updates, log, placements


def _spawn(board, catalogs, quest, game_state, updates, placements, say, *, why: str) -> None:
    heroes = living_heroes(game_state)
    occupied = {tuple(h["pos"]) for h in heroes} | {
        tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")
    }
    revealed = revealed_squares(board, game_state.get("revealed", {}))
    spawn = spawn_wandering_monster_from_turn_roll(board, quest, revealed, quest.get("doors", []), occupied, heroes)
    if spawn is None:
        return
    monsters = game_state.setdefault("monsters", {})
    new_id = _next_wandering_id(set(monsters))
    body = catalogs.monsters.get(spawn["type"], {}).get("body", 1)
    monsters[new_id] = {"type": spawn["type"], "pos": list(spawn["pos"]), "currentBody": body, "alive": True}
    updates[f"monsters.{new_id}"] = monsters[new_id]
    placements.append(spawn["placementInstruction"])
    say(f"{why}: a {monster_display_name(spawn['type'])} prowls the dungeon. {spawn['placementInstruction']}")
