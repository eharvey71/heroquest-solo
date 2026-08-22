"""Plays one simulated quest to a win, a wipe, or a timeout.

Zargon's whole side is the REAL engine -- movement, targeting, turn
types, combat, traps, fog. That is what makes the numbers worth
anything: the thing being measured is the code that ships.

The heroes are the model. A scripted party walks toward the objective,
opens what it finds, fights what it meets, and walks home. It never
retreats, never drinks a potion, never casts a spell, and carries its
starting weapon all quest (see sim/heroes.py). So the absolute win rate
is pessimistic; what the sim is FOR is the difference between two runs
over the same seeds with one rule changed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from engine.combat import resolve_hero_attack, roll_monster_attack  # noqa: F401 (roll lives in the engine)
from engine.create_game import build_initial_game_state
from engine.dice import roll_attack, roll_hero_defend
from engine.doors import InvalidDoorOpenError, resolve_open_door
from engine.end_turn import resolve_end_turn
from engine.hero_movement import IllegalMovementError, resolve_hero_movement
from engine.hero_status import add_status, attempt_break, blocking_status, expire_turn_statuses
from engine.heroes import living_heroes, record_hero_death
from engine.movement import find_path, passable_door_edges, squares_adjacent_to
from engine.objective import check_objective_complete, hero_on_stairway
from engine.targeting import roll_turn_type
from engine.zargon_turn import resolve_zargon_turn
from validator.geometry import footprint_cells, furniture_squares

from .heroes import HeroCard, party_for

Coord = tuple[int, int]

MAX_TURNS = 60
TRAP_DAMAGE = {"pit": 1, "spear": 1}


@dataclass
class Outcome:
    result: str  # "won" | "wiped" | "timeout"
    turns: int
    heroes_lost: int
    monsters_killed: int
    seed: int
    # Body Points the party lost over the quest. Far more sensitive than
    # the win rate, which saturates at 100% for a healthy 4-hero party --
    # a rule that makes monsters harder to kill shows up here first.
    damage_taken: int = 0
    log: list[str] = field(default_factory=list)

    @property
    def won(self) -> bool:
        return self.result == "won"


def _hero_walkable(board, catalogs, quest, game_state) -> set[Coord]:
    """Squares a hero could stand on: the whole board minus terrain that
    never opens up. Deliberately NOT limited to revealed squares -- fog
    is the party's ignorance, not a wall, and walking into it is how the
    map gets revealed.
    """
    blocked = {tuple(s) for s in quest.get("blockedSquares", [])}
    blocked |= {tuple(s) for s in game_state.get("collapsedSquares", [])}
    blocked |= furniture_squares(quest, catalogs)
    return {sq for sq in board.area_of if sq not in blocked}


def _door_at(quest, game_state, pos: Coord) -> str | None:
    """The id of a closed door the hero is standing at, if any. Doors are
    opened FROM the doorway (CLAUDE.md), so this is where a hero acts.
    """
    for door in quest.get("doors", []):
        state = game_state.get("doors", {}).get(door["id"], door.get("state"))
        if state == "closed" and pos in {tuple(sq) for sq in door["squares"]}:
            return door["id"]
    return None


def _open_door(board, quest, game_state, hero_id: str, door_id: str) -> None:
    try:
        result = resolve_open_door(
            board=board, quest=quest, game_state=game_state, hero_id=hero_id, door_id=door_id
        )
    except InvalidDoorOpenError:
        return
    game_state.setdefault("doors", {})[result.door_id] = result.new_state
    if result.revealed_room:
        game_state["revealed"]["rooms"] = sorted(set(game_state["revealed"]["rooms"]) | {result.revealed_room})


# How far a party will go out of its way for a monster it can see. Two
# turns' movement: further than that and they press on with the quest
# instead, which is what a table does.
ENGAGE_RANGE = 14


def _visible_monster_squares(board, game_state) -> set[Coord]:
    """Squares next to monsters the party has actually uncovered. A
    party fights what it meets; it doesn't march past a live orc.
    """
    revealed_rooms = set(game_state.get("revealed", {}).get("rooms", []))
    revealed_corridor = {tuple(sq) for sq in game_state.get("revealed", {}).get("corridorSquares", [])}
    squares: set[Coord] = set()
    for m in game_state.get("monsters", {}).values():
        if not m.get("alive"):
            continue
        pos = tuple(m["pos"])
        area = board.area_of.get(pos)
        if area in revealed_rooms or pos in revealed_corridor:
            squares |= squares_adjacent_to(pos)
    return squares


def _closed_door_squares(quest, game_state) -> set[Coord]:
    squares: set[Coord] = set()
    for door in quest.get("doors", []):
        state = game_state.get("doors", {}).get(door["id"], door.get("state"))
        if state == "closed":
            squares.update(tuple(sq) for sq in door["squares"])
    return squares


def _goal_squares(board, quest, game_state, objective_done: bool) -> set[Coord]:
    """Where the party is trying to get to.

    The party does NOT know where the objective is until it has opened
    the door on it -- handing the sim the boss's coordinates turned every
    quest into a 16-turn straight line past most of the dungeon, which is
    exactly the content whose difficulty is being measured. So: explore
    (walk at the nearest closed door) until the objective's room has
    actually been revealed, then go for it, then walk home.
    """
    if objective_done:
        return set(footprint_cells(tuple(quest["stairway"]["pos"]), (2, 2)))

    target = quest.get("objective", {}).get("target", {})
    room = target.get("room")
    revealed_rooms = set(game_state.get("revealed", {}).get("rooms", []))

    if room in revealed_rooms:
        monster_id = target.get("monsterId")
        boss = game_state.get("monsters", {}).get(monster_id) if monster_id else None
        if boss and boss.get("alive"):
            return squares_adjacent_to(tuple(boss["pos"]))
        return set(board.room_squares.get(room, ()))

    doors = _closed_door_squares(quest, game_state)
    return doors or set(board.room_squares.get(room, ()))


def _adjacent_monster(game_state, hero_pos: Coord) -> str | None:
    neighbours = squares_adjacent_to(hero_pos)
    for mid, m in sorted(game_state.get("monsters", {}).items()):
        if m.get("alive") and tuple(m["pos"]) in neighbours:
            return mid
    return None


def _monster_stats(quest, catalogs, monster_id):
    for room in quest.get("rooms", {}).values():
        for m in room.get("monsters", []):
            if m["id"] == monster_id:
                entry = catalogs.monsters[m["type"]]
                overrides = m.get("overrides", {})
                return m.get("name") or m["type"], overrides.get("defend", entry["defend"])
    return "wandering monster", catalogs.monsters["orc"]["defend"]


def _hero_attacks(quest, catalogs, game_state, card: HeroCard, monster_id: str, rng) -> bool:
    """Returns True if the monster died."""
    state = game_state["monsters"][monster_id]
    name, defend_dice = _monster_stats(quest, catalogs, monster_id)
    result = resolve_hero_attack(
        monster_name=name,
        monster_defend_dice=defend_dice,
        skulls=roll_attack(card.attack_dice, rng),
        current_body=state["currentBody"],
        rng=rng,
    )
    state["currentBody"] = result.body_points_after
    state["alive"] = not result.defeated
    return result.defeated


def _take_hero_turn(board, catalogs, quest, game_state, card: HeroCard, body: dict, rng) -> int:
    """One hero's full turn: move, then act. Returns monsters killed."""
    hero = next((h for h in living_heroes(game_state) if h["id"] == card.id), None)
    if hero is None:
        return 0

    # Held by a Chaos spell: the turn goes on shaking it off instead --
    # one red die per Mind Point, a 6 frees them (engine/hero_status.py).
    if blocking_status(game_state, card.id) is not None:
        rolled_six = any(rng.randint(1, 6) == 6 for _ in range(card.mind))
        try:
            attempt_break(game_state, card.id, card.name, rolled_six)
        except Exception:  # noqa: BLE001 -- becalmed can't be rolled against
            pass
        return 0

    killed = 0
    # In contact already? Then fighting is the whole turn.
    engaged = _adjacent_monster(game_state, tuple(hero["pos"]))
    if engaged:
        return 1 if _hero_attacks(quest, catalogs, game_state, card, engaged, rng) else 0

    # Standing at a closed door -- opening it is this turn's action, and
    # it is how the party gets out of the stairway room at all.
    standing_at = _door_at(quest, game_state, tuple(hero["pos"]))
    if standing_at:
        _open_door(board, quest, game_state, card.id, standing_at)
        return killed

    objective_done = game_state.get("objectiveComplete") or check_objective_complete(quest, game_state)
    goals = _goal_squares(board, quest, game_state, objective_done)
    door_edges = passable_door_edges(quest.get("doors", []), game_state.get("doors", {}))
    occupied = {tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")}

    walkable = _hero_walkable(board, catalogs, quest, game_state)

    # Anything uncovered and close gets dealt with first; the objective
    # is what you walk toward when nothing is in your face.
    nearby = _visible_monster_squares(board, game_state) - {tuple(hero["pos"])}
    path = None
    if nearby:
        to_monster = find_path(board, walkable, door_edges, occupied, tuple(hero["pos"]), nearby)
        if to_monster is not None and len(to_monster) - 1 <= ENGAGE_RANGE:
            path = to_monster
    if path is None:
        path = find_path(board, walkable, door_edges, occupied, tuple(hero["pos"]), goals)
    if path is None:
        # Whatever the party was heading for is walled off behind a door
        # it hasn't opened yet -- go open one.
        path = find_path(
            board, walkable, door_edges, occupied, tuple(hero["pos"]), _closed_door_squares(quest, game_state)
        )
    if path is None or len(path) < 2:
        return killed

    # 2d6 movement, the same red dice the player rolls at the table. A
    # hero may pass THROUGH a fellow hero but never stop on one, so back
    # off a step at a time until the landing square is free.
    steps = min(rng.randint(1, 6) + rng.randint(1, 6), len(path) - 1)
    others = {tuple(h["pos"]) for h in living_heroes(game_state) if h["id"] != card.id}
    while steps > 0 and path[steps] in others:
        steps -= 1
    if steps == 0:
        return killed
    try:
        result = resolve_hero_movement(
            board=board, catalogs=catalogs, quest=quest, game_state=game_state,
            hero_id=card.id, path=[list(p) for p in path[: steps + 1]],
        )
    except IllegalMovementError:
        return killed

    hero["pos"] = list(result.final_pos)
    game_state["revealed"]["rooms"] = sorted(result.revealed_rooms)
    game_state["revealed"]["corridorSquares"] = [list(sq) for sq in sorted(result.revealed_corridor_squares)]
    game_state["trapsTriggered"] = sorted(result.traps_triggered)
    game_state["collapsedSquares"] = [list(sq) for sq in sorted(result.collapsed_squares)]

    for trap in result.triggered_traps:
        if trap.trap_type == "falling_block":
            body[card.id] -= roll_attack(3, rng)
        else:
            body[card.id] -= TRAP_DAMAGE.get(trap.trap_type, 1)

    # Walked up to a closed door: opening it is the action.
    if result.stopped_reason == "closed_door" and result.stopped_at_door_id:
        _open_door(board, quest, game_state, card.id, result.stopped_at_door_id)
        return killed

    engaged = _adjacent_monster(game_state, tuple(hero["pos"]))
    if engaged and _hero_attacks(quest, catalogs, game_state, card, engaged, rng):
        killed += 1
    return killed


def _apply_chaos_casts(catalogs, game_state, result, body: dict, cards: dict, turn: int, rng) -> None:
    """What a spell does to the sim's own bookkeeping. The engine decided
    all of it; this is the sim playing the part main.py plays in the app.
    """
    for cast in getattr(result, "chaos_casts", []):
        game_state.setdefault("chaosSpellsCast", []).append(cast.spell_id)

        for hit in cast.hero_hits:
            saved = sum(1 for _ in range(hit.get("reductionDice", 0)) if rng.randint(1, 6) >= 5)
            body[hit["heroId"]] -= max(0, hit["damage"] - saved)

        for monster_id, damage in cast.monster_damage.items():
            state = game_state["monsters"].get(monster_id)
            if state is None:
                continue
            state["currentBody"] = max(0, state["currentBody"] - damage)
            state["alive"] = state["currentBody"] > 0

        for status in cast.statuses:
            add_status(
                game_state, status["heroId"], status=status["status"],
                spell=cast.spell_id, turn=turn, misses_turns=status.get("missesTurns", 0),
            )

        for index, summon in enumerate(cast.summons):
            new_id = f"C{len(game_state['monsters']) + index + 1}"
            game_state["monsters"][new_id] = {
                "type": summon["type"],
                "pos": list(summon["pos"]),
                "currentBody": catalogs.monsters[summon["type"]]["body"],
                "alive": True,
            }


def _apply_zargon_attacks(game_state, result, body: dict, cards: dict, rng) -> None:
    for mr in result.monster_results:
        attack = mr.turn_result.attack if mr.turn_result else None
        if attack is None:
            continue
        hero = next((h for h in living_heroes(game_state) if h.get("name") == attack.hero_name), None)
        if hero is None:
            continue
        card = cards[hero["id"]]
        blocks = roll_hero_defend(card.defend_dice, rng)
        body[card.id] -= max(0, attack.skulls - blocks)


def _bury_the_dead(game_state, body: dict) -> int:
    fallen = 0
    for hero in list(living_heroes(game_state)):
        if body[hero["id"]] <= 0:
            record_hero_death(game_state, hero["id"])
            fallen += 1
    return fallen


def play_quest(
    catalogs,
    quest: dict,
    hero_count: int,
    *,
    withdraw_policy: str,
    seed: int = 0,
    max_turns: int = MAX_TURNS,
) -> Outcome:
    rng = random.Random(seed)
    board = catalogs.board

    cards = {c.id: c for c in party_for(hero_count)}
    game_state = build_initial_game_state(
        quest=quest, catalogs=catalogs, heroes=[{"id": c.id, "name": c.name} for c in cards.values()]
    )
    body = {c.id: c.body for c in cards.values()}

    heroes_lost = 0
    monsters_killed = 0
    starting_body = sum(body.values())

    for turn in range(1, max_turns + 1):
        game_state["turn"] = turn
        game_state["phase"] = "hero"
        game_state["heroPhaseSegment"] = 1

        # A lone hero acts twice per turn -- the balance rule, enforced
        # here the same way end_turn.py enforces it in the real app.
        while True:
            for card in list(cards.values()):
                monsters_killed += _take_hero_turn(board, catalogs, quest, game_state, card, body, rng)
            heroes_lost += _bury_the_dead(game_state, body)
            if not living_heroes(game_state):
                return Outcome("wiped", turn, heroes_lost, monsters_killed, seed,
                               damage_taken=starting_body - sum(body.values()))
            expire_turn_statuses(game_state, turn)
            phase = resolve_end_turn(game_state)
            game_state["phase"] = phase.new_phase
            game_state["heroPhaseSegment"] = phase.new_segment
            if phase.new_phase != "hero":
                break

        if check_objective_complete(quest, game_state):
            game_state["objectiveComplete"] = True
            if hero_on_stairway(quest, game_state):
                return Outcome("won", turn, heroes_lost, monsters_killed, seed,
                               damage_taken=starting_body - sum(body.values()))

        turn_type = roll_turn_type(hero_count, "standard", rng=rng)
        result = resolve_zargon_turn(
            board=board,
            catalogs=catalogs,
            quest=quest,
            game_state=game_state,
            turn_type=turn_type,
            lowest_bp_hero_id=min(
                (h["id"] for h in living_heroes(game_state)), key=lambda hid: body[hid], default=None
            ),
            withdraw_policy=withdraw_policy,
            rng=rng,
        )
        for mid, pos in result.updated_monster_positions.items():
            game_state["monsters"][mid]["pos"] = list(pos)
        if result.spawned_monster:
            spawn = result.spawned_monster
            new_id = f"W{len([m for m in game_state['monsters'] if m.startswith('W')]) + 1}"
            game_state["monsters"][new_id] = {
                "type": spawn["type"],
                "pos": list(spawn["pos"]),
                "currentBody": catalogs.monsters[spawn["type"]]["body"],
                "alive": True,
            }

        _apply_chaos_casts(catalogs, game_state, result, body, cards, turn, rng)
        _apply_zargon_attacks(game_state, result, body, cards, rng)
        heroes_lost += _bury_the_dead(game_state, body)
        if not living_heroes(game_state):
            return Outcome("wiped", turn, heroes_lost, monsters_killed, seed,
                               damage_taken=starting_body - sum(body.values()))

    return Outcome(
        "timeout", max_turns, heroes_lost, monsters_killed, seed,
        damage_taken=starting_body - sum(body.values()),
    )
