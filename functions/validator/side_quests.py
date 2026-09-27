"""Shape checks for generated side quests (design/side-quests-design.md
section 11). Same contract as the quest validator: plain lists of
machine-readable error strings the retry loop hands straight back to
the model, every check defensive about malformed input so all errors
surface in one pass.

The graph rules are what make a scene safe to play: every path reaches
an ending, no party composition is dead-ended, the one retry edge is
the only cycle, and a required scene can always be won by a party with
no tagged hero at all. The effect caps are what keep the model from
handing out too much.
"""

from __future__ import annotations

import re

from engine.side_quests import (
    COST_KINDS,
    EFFECT_POINTS,
    EFFECT_TYPES,
    ELEMENTS,
    HERO_IDS,
    HOOK_WHENS,
    KINDS,
    OUTCOMES,
    REWARD_KINDS,
    REWARD_POINTS,
    SETTINGS,
    TEST_KINDS,
)

from .balance import _door_hop_depth, _monster_threat_cost
from .reachability import _objective_target_room

MIN_NODES = 5
MAX_NODES = 10
MAX_DEPTH = 7
MIN_CHOICES = 2
MAX_CHOICES = 3
MAX_PASSAGE_WORDS = 140
OPTIONAL_BEST_MAX = 4
WORST_MIN = -2
REQUIRED_EXTRA_MAX = 2
MAX_SIDE_QUESTS = 3

_ROOM_ID = re.compile(r"\bR\d+\b")
_COORD = re.compile(r"\[\s*\d+\s*,\s*\d+\s*\]")
_ID_LIKE = re.compile(r"\b(?:[MW]\d+|R\d+-T\d+|CORRIDOR-T\d+)\b")


def _prose_problems(text: str, where: str) -> list[str]:
    errors = []
    if not isinstance(text, str):
        return [f"{where} must be a string"]
    if _ROOM_ID.search(text) or _COORD.search(text) or _ID_LIKE.search(text):
        errors.append(f"{where} prints a room id, square coordinate or monster/trap id -- use narrative language")
    return errors


def _placed_artifacts(quest: dict) -> set[str]:
    placed = set()
    artifact_id = quest.get("objective", {}).get("target", {}).get("artifactId")
    if artifact_id:
        placed.add(artifact_id)
    for room in quest.get("rooms", {}).values():
        for piece in room.get("furniture", []):
            artifact_id = (piece.get("contains") or {}).get("artifactId")
            if artifact_id:
                placed.add(artifact_id)
    return placed


def _quest_monsters(quest: dict) -> dict:
    out = {}
    for room in quest.get("rooms", {}).values():
        for m in room.get("monsters", []):
            if m.get("id"):
                out[m["id"]] = m
    return out


def _effect_points(effect: dict, quest: dict, catalogs) -> int:
    etype = effect.get("type")
    if etype == "announce_reward":
        return REWARD_POINTS.get(effect.get("kind"), 1)
    if etype == "remove_monster":
        m = _quest_monsters(quest).get(effect.get("monsterId"))
        entry = catalogs.monsters.get((m or {}).get("type")) if m else None
        return max(1, _monster_threat_cost(m, entry) // 4) if entry else 2
    return EFFECT_POINTS.get(etype, 0)


def check_side_quests(side_quests, quest: dict, catalogs, *, required_gate: dict | None) -> list:
    errors: list[str] = []
    if not isinstance(side_quests, list):
        return ["sideQuests must be an array"]
    if not 1 <= len(side_quests) <= MAX_SIDE_QUESTS:
        errors.append(f"there must be 1-{MAX_SIDE_QUESTS} side quests, got {len(side_quests)}")

    kinds = [sq.get("kind") for sq in side_quests if isinstance(sq, dict)]
    required_count = kinds.count("required")
    optional_count = kinds.count("optional")
    if required_gate and required_count != 1:
        errors.append(f"exactly one side quest must be 'required' (the server asked for one), got {required_count}")
    if not required_gate and required_count:
        errors.append("no side quest may be 'required' -- the server did not ask for one this time")
    if not 1 <= optional_count <= 2:
        errors.append(f"there must be 1-2 'optional' side quests, got {optional_count}")

    ids = [sq.get("id") for sq in side_quests if isinstance(sq, dict)]
    if len(set(ids)) != len(ids):
        errors.append("side quest ids must be unique")

    placed_artifacts = _placed_artifacts(quest)
    granted_artifacts: dict[str, str] = {}
    for sq in side_quests:
        if not isinstance(sq, dict):
            errors.append("each side quest must be an object")
            continue
        errors += _check_one(sq, quest, catalogs, required_gate, placed_artifacts, granted_artifacts)
    return errors


def _check_one(sq: dict, quest: dict, catalogs, required_gate, placed_artifacts: set, granted: dict) -> list:
    errors: list[str] = []
    sq_id = sq.get("id") or "?"
    where = f"side quest {sq_id}"

    if sq.get("kind") not in KINDS:
        errors.append(f"{where}: kind must be one of {KINDS}")
    if sq.get("setting") not in SETTINGS:
        errors.append(f"{where}: setting must be one of {SETTINGS}")
    if not sq.get("title"):
        errors.append(f"{where}: needs a title")
    errors += _prose_problems(sq.get("title", ""), f"{where} title")

    # -- hook --
    hook = sq.get("hook") or {}
    when = hook.get("when")
    if when not in HOOK_WHENS:
        errors.append(f"{where}: hook.when must be one of {HOOK_WHENS}")
    hook_room = hook.get("room") or ""
    objective_room = _objective_target_room(quest, catalogs.board)
    stair_room = quest.get("stairway", {}).get("room")
    if when == "room":
        if hook_room not in quest.get("rooms", {}):
            errors.append(f"{where}: hook.room must be one of this quest's populated rooms, got '{hook_room}'")
        elif hook_room == objective_room:
            errors.append(f"{where}: hook.room must not be the objective's own room")
        elif sq.get("kind") == "required" and stair_room and objective_room:
            hook_depth = _door_hop_depth(catalogs, quest, stair_room, hook_room)
            goal_depth = _door_hop_depth(catalogs, quest, stair_room, objective_room)
            if hook_depth is None or (goal_depth is not None and hook_depth >= goal_depth):
                errors.append(
                    f"{where}: a required side quest's hook room must be met BEFORE the objective room "
                    f"(fewer doors from the stairway than {objective_room})"
                )
    elif when == "prologue" and hook_room:
        errors.append(f"{where}: a prologue hook has no room -- set hook.room to \"\"")
    errors += _prose_problems(hook.get("text", ""), f"{where} hook.text")
    if not hook.get("text"):
        errors.append(f"{where}: hook.text (how the scene is offered) is required")

    if sq.get("kind") == "required" and not sq.get("gateText"):
        errors.append(f"{where}: a required side quest needs gateText (why the finale is barred)")
    errors += _prose_problems(sq.get("gateText", ""), f"{where} gateText")

    # -- nodes --
    passages = sq.get("passages") or {}
    terminals = sq.get("terminals") or {}
    if not isinstance(passages, dict) or not isinstance(terminals, dict):
        return errors + [f"{where}: passages and terminals must be present"]
    overlap = set(passages) & set(terminals)
    if overlap:
        errors.append(f"{where}: ids used both as a passage and a terminal: {sorted(overlap)}")
    node_count = len(passages) + len(terminals)
    if not MIN_NODES <= node_count <= MAX_NODES:
        errors.append(f"{where}: {node_count} passages+terminals, must be {MIN_NODES}-{MAX_NODES}")
    if not terminals:
        errors.append(f"{where}: needs at least one terminal")
    start = sq.get("start")
    if start not in passages:
        errors.append(f"{where}: start must name a passage, got '{start}'")

    edges: dict[str, list[tuple[str, bool]]] = {}  # node -> [(target, untagged)]
    for pid, passage in passages.items():
        errors += _prose_problems(passage.get("text", ""), f"{where} passage {pid}")
        words = len((passage.get("text") or "").split())
        if words > MAX_PASSAGE_WORDS:
            errors.append(f"{where} passage {pid}: {words} words, keep it under {MAX_PASSAGE_WORDS}")
        if words == 0:
            errors.append(f"{where} passage {pid}: has no text")
        choices = passage.get("choices") or []
        if not MIN_CHOICES <= len(choices) <= MAX_CHOICES:
            errors.append(f"{where} passage {pid}: {len(choices)} choices, must be {MIN_CHOICES}-{MAX_CHOICES}")
        untagged = 0
        seen_choice_ids = set()
        for choice in choices:
            cid = choice.get("id") or "?"
            if cid in seen_choice_ids:
                errors.append(f"{where} passage {pid}: duplicate choice id '{cid}'")
            seen_choice_ids.add(cid)
            errors += _prose_problems(choice.get("label", ""), f"{where} passage {pid} choice {cid} label")
            tagged = bool(choice.get("requiresHero") or choice.get("requiresElement") or choice.get("requiresFlag"))
            if choice.get("requiresHero") and choice["requiresHero"] not in HERO_IDS:
                errors.append(f"{where} passage {pid} choice {cid}: requiresHero must be one of {HERO_IDS}")
            if choice.get("requiresElement") and choice["requiresElement"] not in ELEMENTS:
                errors.append(f"{where} passage {pid} choice {cid}: requiresElement must be one of {ELEMENTS}")
            if not tagged:
                untagged += 1
            test = choice.get("test") or {}
            kind = test.get("kind")
            if kind and kind != "none":
                if kind not in TEST_KINDS:
                    errors.append(f"{where} passage {pid} choice {cid}: test.kind must be one of {TEST_KINDS}")
                dice = test.get("dice")
                need = test.get("needSkulls")
                if kind in ("combat_dice", "zargon"):
                    if not isinstance(dice, int) or not 1 <= dice <= 3:
                        errors.append(f"{where} passage {pid} choice {cid}: test.dice must be 1-3")
                    if not isinstance(need, int) or not 1 <= need <= (dice if isinstance(dice, int) else 3):
                        errors.append(f"{where} passage {pid} choice {cid}: test.needSkulls must be 1..dice")
                for branch in ("success", "failure"):
                    target = test.get(branch)
                    if target not in passages and target not in terminals:
                        errors.append(f"{where} passage {pid} choice {cid}: test.{branch} must name a node, got '{target}'")
                    else:
                        edges.setdefault(pid, []).append((target, not tagged))
            else:
                target = choice.get("next")
                if target not in passages and target not in terminals:
                    errors.append(f"{where} passage {pid} choice {cid}: next must name a node, got '{target}'")
                else:
                    edges.setdefault(pid, []).append((target, not tagged))
        if untagged == 0 and choices:
            errors.append(f"{where} passage {pid}: every passage needs at least one choice with no hero/element/flag requirement")

    # -- the one allowed cycle --
    retry = sq.get("retry") or None
    retry_edge = None
    if retry and retry.get("from"):
        r_from, r_to = retry.get("from"), retry.get("to")
        if r_from not in passages or r_to not in passages:
            errors.append(f"{where}: retry.from and retry.to must both name passages")
        elif not any(t == r_to for t, _ in edges.get(r_from, [])):
            errors.append(f"{where}: retry ({r_from} -> {r_to}) must be an edge some choice in {r_from} actually takes")
        else:
            retry_edge = (r_from, r_to)
        if not retry.get("costText"):
            errors.append(f"{where}: a retry needs costText (what the second attempt costs)")
        errors += _prose_problems(retry.get("costText", ""), f"{where} retry.costText")

    if start in passages:
        errors += _graph_problems(where, start, passages, terminals, edges, retry_edge)

    # -- terminals and effects --
    best = None
    worst = None
    has_success = False
    quest_monsters = _quest_monsters(quest)
    boss_id = quest.get("objective", {}).get("target", {}).get("monsterId")
    for tid, terminal in terminals.items():
        outcome = terminal.get("outcome")
        if outcome not in OUTCOMES:
            errors.append(f"{where} terminal {tid}: outcome must be one of {OUTCOMES}")
        errors += _prose_problems(terminal.get("text", ""), f"{where} terminal {tid}")
        if not terminal.get("text"):
            errors.append(f"{where} terminal {tid}: needs epilogue text")
        effects = terminal.get("effects") or []
        types = [e.get("type") for e in effects]
        points = 0
        gate_points = 0
        for effect in effects:
            etype = effect.get("type")
            ewhere = f"{where} terminal {tid} effect {etype}"
            if etype not in EFFECT_TYPES:
                errors.append(f"{ewhere}: unknown effect type (allowed: {EFFECT_TYPES})")
                continue
            if etype in ("break_gate", "crack_gate"):
                if sq.get("kind") != "required":
                    errors.append(f"{ewhere}: only a required side quest touches the gate")
                gate_points += 1
                continue
            if etype in ("weaken_monster", "remove_monster"):
                mid = effect.get("monsterId")
                if mid not in quest_monsters:
                    errors.append(f"{ewhere}: monsterId must be one of this quest's monsters, got '{mid}'")
                elif etype == "remove_monster" and mid == boss_id:
                    errors.append(f"{ewhere}: the objective's boss cannot be removed by a side quest")
                if etype == "weaken_monster" and effect.get("stat") not in ("body", "defend"):
                    errors.append(f"{ewhere}: stat must be 'body' or 'defend'")
            if etype in ("reveal_traps", "reveal_secret_doors") and effect.get("room") not in quest.get("rooms", {}):
                errors.append(f"{ewhere}: room must be one of this quest's populated rooms, got '{effect.get('room')}'")
            if etype == "grant_artifact":
                aid = effect.get("artifactId")
                if aid not in catalogs.artifacts:
                    errors.append(f"{ewhere}: unknown artifactId '{aid}'")
                elif aid in placed_artifacts or (aid in granted and granted[aid] != sq_id):
                    errors.append(f"{ewhere}: artifact '{aid}' is already placed elsewhere -- there is one card of each")
                else:
                    granted[aid] = sq_id
            if etype == "miss_turn" and effect.get("heroId") and effect["heroId"] not in HERO_IDS:
                errors.append(f"{ewhere}: heroId must be one of {HERO_IDS} or empty")
            if etype == "announce_reward":
                if effect.get("kind") not in REWARD_KINDS:
                    errors.append(f"{ewhere}: kind must be one of {REWARD_KINDS}")
                if not effect.get("text"):
                    errors.append(f"{ewhere}: needs text saying what the party gains")
            if etype == "announce_cost":
                if effect.get("kind") not in COST_KINDS:
                    errors.append(f"{ewhere}: kind must be one of {COST_KINDS}")
                if not effect.get("text"):
                    errors.append(f"{ewhere}: needs text saying what it costs")
            if etype == "armory_visit" and sq.get("setting") != "town":
                errors.append(f"{ewhere}: only a town scene visits the Armory")
            errors += _prose_problems(effect.get("text", "") or "", ewhere)
            points += _effect_points(effect, quest, catalogs)
        if sq.get("setting") == "town" and "armory_visit" not in types:
            errors.append(f"{where} terminal {tid}: a town scene must include the armory_visit beat")
        if sq.get("kind") == "required" and outcome == "success" and "break_gate" not in types:
            errors.append(f"{where} terminal {tid}: a required side quest's success must include break_gate")
        if sq.get("kind") == "required" and outcome != "success" and "break_gate" in types:
            errors.append(f"{where} terminal {tid}: break_gate belongs on a success terminal only")
        if outcome == "success":
            has_success = True
        best = points if best is None else max(best, points)
        worst = points if worst is None else min(worst, points)

    if not has_success:
        errors.append(f"{where}: needs at least one success terminal")
    if best is not None:
        cap = REQUIRED_EXTRA_MAX if sq.get("kind") == "required" else OPTIONAL_BEST_MAX
        if best > cap:
            errors.append(f"{where}: the best ending is worth {best} boon points, cap is {cap}")
        if worst is not None and worst < WORST_MIN:
            errors.append(f"{where}: the worst ending costs {worst} points, floor is {WORST_MIN}")
    return errors


def _graph_problems(where, start, passages, terminals, edges, retry_edge) -> list:
    """Acyclic apart from the declared retry edge; every terminal
    reachable; every passage reaches a terminal; depth <= MAX_DEPTH;
    and for the required scene, a success terminal reachable through
    untagged choices only."""
    errors = []

    def out(node, untagged_only=False, drop_retry=True):
        for target, untagged in edges.get(node, []):
            if drop_retry and retry_edge and (node, target) == retry_edge:
                continue
            if untagged_only and not untagged:
                continue
            yield target

    # cycles (DFS colouring), retry edge excluded
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {n: WHITE for n in list(passages) + list(terminals)}
    cyclic = False

    def dfs(n):
        nonlocal cyclic
        colour[n] = GREY
        for t in out(n):
            if colour.get(t) == GREY:
                cyclic = True
            elif colour.get(t) == WHITE:
                dfs(t)
        colour[n] = BLACK

    for n in passages:
        if colour[n] == WHITE:
            dfs(n)
    if cyclic:
        errors.append(f"{where}: the passages loop -- only the single declared retry edge may lead backwards")
        return errors

    # reachability from start
    reach = set()
    stack = [start]
    while stack:
        n = stack.pop()
        if n in reach:
            continue
        reach.add(n)
        stack.extend(out(n, drop_retry=False))
    unreachable_terminals = sorted(t for t in terminals if t not in reach)
    if unreachable_terminals:
        errors.append(f"{where}: terminals never reached from start: {unreachable_terminals}")
    unreachable_passages = sorted(p for p in passages if p not in reach)
    if unreachable_passages:
        errors.append(f"{where}: passages never reached from start: {unreachable_passages}")

    # every passage reaches some terminal; longest path
    memo: dict[str, int] = {}

    def depth_to_end(n):
        if n in terminals:
            return 0
        if n in memo:
            return memo[n]
        best = None
        for t in out(n):
            d = depth_to_end(t)
            if d is not None:
                best = d + 1 if best is None else max(best, d + 1)
        memo[n] = best
        return best

    dead = sorted(p for p in passages if depth_to_end(p) is None)
    if dead:
        errors.append(f"{where}: passages with no route to any ending: {dead}")
    longest = depth_to_end(start)
    if longest is not None and longest > MAX_DEPTH:
        errors.append(f"{where}: the longest route is {longest} passages deep, keep it to {MAX_DEPTH}")

    # untagged route to a success terminal
    reach_untagged = set()
    stack = [start]
    while stack:
        n = stack.pop()
        if n in reach_untagged:
            continue
        reach_untagged.add(n)
        stack.extend(out(n, untagged_only=True))
    if not any(terminals[t].get("outcome") == "success" for t in reach_untagged if t in terminals):
        errors.append(
            f"{where}: a success ending must be reachable using only choices with no hero/element/flag requirement"
        )
    return errors
