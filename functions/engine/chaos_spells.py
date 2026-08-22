"""Zargon's twelve Chaos spell cards.

Rules text, verbatim from the owner's 1989 cards, lives in
data/chaos_spells.json -- this module is only the resolution.

    "As Zargon, you may cast a spell instead of attacking, like the elf
    and wizard. You must give your Chaos spells to specific monsters
    called for in the Quest notes. A monster can only cast a spell on a
    Hero that it can 'see'. You may only cast a spell on your turn. A
    spell may only be cast once per Quest. After casting the spell is
    discarded, like the Hero spells."

So: the quest assigns spells to named monsters (quest schema's
monster.spells), a caster spends one INSTEAD of attacking, the target
must pass the real line-of-sight test (engine/line_of_sight.py), and a
spent card never comes back (game state's chaosSpellsCast).

Where the physical/digital line falls, per CLAUDE.md's boundary:

- Damage to MONSTERS is applied here; Body Points are digital for them.
- Damage to HEROES is announced, never tracked -- the hero sheet is
  physical. Where a card says "the Hero immediately rolls two red dice",
  those are the hero's own dice, so the app names the roll and the
  player applies whatever it saves them.
- Equipment (Rust) and Mind Points (every "roll one red die for each of
  his Mind Points") are physical too. Rust is narrated; break attempts
  are their own action (engine/hero_status.py).
- Summons, teleports, statuses and monster damage are the app's -- it
  moves figures, spawns minis and enforces who may act.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from validator.catalogs import CORRIDOR, Board, Catalogs

from .line_of_sight import has_line_of_sight
from .movement import passable_door_edges, squares_adjacent_to

Coord = tuple[int, int]

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "chaos_spells.json"

# Every direction a Lightning Bolt may travel: "horizontal, vertical, or
# diagonal" (the card), which is the one place in this engine where
# diagonals are legal.
_BOLT_DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


class UnknownChaosSpellError(ValueError):
    """No such card."""


class ChaosSpellUnavailableError(ValueError):
    """Already cast this quest, or not one this monster was given."""


@dataclass
class HeroHit:
    hero_id: str
    hero_name: str
    damage: int
    reduction_dice: int = 0


@dataclass
class ChaosSpellResult:
    spell_id: str
    spell_name: str
    caster_id: str
    hero_hits: list[HeroHit] = field(default_factory=list)
    monster_damage: dict = field(default_factory=dict)  # monsterId -> body points
    statuses: list[dict] = field(default_factory=list)  # {heroId, heroName, status}
    summons: list[dict] = field(default_factory=list)  # {type, pos}
    caster_new_pos: Coord | None = None
    placement_instructions: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


def load_chaos_spells(path: Path | None = None) -> dict:
    return json.loads((path or DATA_PATH).read_text())


CHAOS_SPELLS = load_chaos_spells()


def spell_ids() -> list[str]:
    return sorted(CHAOS_SPELLS)


def _walls(quest: dict, game_state: dict) -> frozenset:
    return frozenset(
        {tuple(sq) for sq in quest.get("blockedSquares", [])}
        | {tuple(sq) for sq in game_state.get("collapsedSquares", [])}
    )


def _figures(game_state: dict, heroes: list[dict]) -> frozenset:
    return frozenset(
        {tuple(h["pos"]) for h in heroes}
        | {tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")}
    )


def visible_heroes(
    board: Board, quest: dict, game_state: dict, heroes: list[dict], caster_pos: Coord
) -> list[dict]:
    """The heroes a caster can SEE -- the card's own requirement, using
    the rulebook sightline (figures block, walls and closed doors block).
    Nearest first, so "one hero" targeting is deterministic.
    """
    open_edges = passable_door_edges(quest.get("doors", []), game_state.get("doors", {}))
    walls = _walls(quest, game_state)
    figures = _figures(game_state, heroes) - {caster_pos}
    seen = []
    for hero in heroes:
        pos = tuple(hero["pos"])
        if has_line_of_sight(
            board, caster_pos, pos, open_door_edges=open_edges, walls=walls, figures=figures - {pos}
        ):
            seen.append(hero)
    return sorted(
        seen,
        key=lambda h: (
            abs(h["pos"][0] - caster_pos[0]) + abs(h["pos"][1] - caster_pos[1]),
            h["pos"][1],
            h["pos"][0],
        ),
    )


def _bolt_path(board: Board, quest: dict, game_state: dict, start: Coord, direction) -> list[Coord]:
    """Squares a Lightning Bolt crosses: a straight line "until it
    strikes a wall or closed door".
    """
    open_edges = passable_door_edges(quest.get("doors", []), game_state.get("doors", {}))
    walls = _walls(quest, game_state)
    dx, dy = direction
    path: list[Coord] = []
    cur = start
    while True:
        nxt = (cur[0] + dx, cur[1] + dy)
        if board.area_of.get(nxt) is None or nxt in walls:
            break
        if dx and dy:
            # A diagonal bolt has to get round the corner: both ways
            # round must be open, same rule sight uses.
            corners = ((cur[0], nxt[1]), (nxt[0], cur[1]))
            if not any(
                _edge_passable(board, cur, mid, open_edges) and _edge_passable(board, mid, nxt, open_edges)
                for mid in corners
            ):
                break
        elif not _edge_passable(board, cur, nxt, open_edges):
            break
        path.append(nxt)
        cur = nxt
    return path


def _edge_passable(board: Board, a: Coord, b: Coord, open_edges) -> bool:
    area_a, area_b = board.area_of.get(a), board.area_of.get(b)
    if area_a is None or area_b is None:
        return False
    return area_a == area_b or frozenset((a, b)) in open_edges


def _free_squares_near(board: Board, origin: Coord, occupied: set, count: int) -> list[Coord]:
    """Squares to stand summoned monsters on, working outward from the
    caster -- "to surround and protect the spellcaster".
    """
    found: list[Coord] = []
    seen = {origin}
    frontier = [origin]
    while frontier and len(found) < count:
        nxt = []
        for square in frontier:
            for neighbour in sorted(squares_adjacent_to(square), key=lambda c: (c[1], c[0])):
                if neighbour in seen or board.area_of.get(neighbour) is None:
                    continue
                seen.add(neighbour)
                nxt.append(neighbour)
                if neighbour not in occupied:
                    found.append(neighbour)
                    if len(found) == count:
                        return found
        frontier = nxt
    return found


def resolve_chaos_spell(
    *,
    board: Board,
    catalogs: Catalogs,
    quest: dict,
    game_state: dict,
    heroes: list[dict],
    caster_id: str,
    caster_name: str,
    caster_pos: Coord,
    spell_id: str,
    rng: random.Random | None = None,
) -> ChaosSpellResult:
    rng = rng or random
    spell = CHAOS_SPELLS.get(spell_id)
    if spell is None:
        raise UnknownChaosSpellError(f"no Chaos spell '{spell_id}'")
    if spell_id in set(game_state.get("chaosSpellsCast", [])):
        raise ChaosSpellUnavailableError(f"{spell['name']} has already been cast this quest")

    result = ChaosSpellResult(spell_id=spell_id, spell_name=spell["name"], caster_id=caster_id)
    result.log.append(f"{caster_name} casts {spell['name']}! {spell['text']}")
    effect = spell["effect"]

    if effect == "narrate_only":
        target = visible_heroes(board, quest, game_state, heroes, caster_pos)[:1]
        who = target[0].get("name", target[0]["id"]) if target else "the party"
        result.log.append(
            f"Zargon picks {who}: take the sword or helmet off their card -- it is ruined for the rest of the quest."
        )
        return result

    if effect == "damage_hero":
        seen = visible_heroes(board, quest, game_state, heroes, caster_pos)
        if not seen:
            raise ChaosSpellUnavailableError("no hero in sight to target")
        hero = seen[0]
        result.hero_hits.append(
            HeroHit(hero["id"], hero.get("name", hero["id"]), spell["damage"], spell.get("reductionDice", 0))
        )
        result.log.append(_hero_damage_line(hero, spell))
        return result

    if effect == "damage_line":
        return _resolve_bolt(board, quest, game_state, heroes, caster_pos, spell, result)

    if effect == "damage_room":
        return _resolve_firestorm(board, catalogs, quest, game_state, heroes, caster_id, caster_pos, spell, result, rng)

    if effect == "status":
        return _resolve_status(board, quest, game_state, heroes, caster_pos, spell, result)

    if effect == "summon":
        return _resolve_summon(board, catalogs, game_state, heroes, caster_pos, spell, result, rng)

    if effect == "teleport_caster":
        destination = quest.get("escapeDestination")
        if not destination:
            raise ChaosSpellUnavailableError("this quest declares no escape destination")
        result.caster_new_pos = (destination[0], destination[1])
        result.log.append(
            f"{caster_name} vanishes and reappears at [{destination[0]},{destination[1]}] -- "
            f"move the figure there."
        )
        return result

    raise UnknownChaosSpellError(f"Chaos spell '{spell_id}' has an unknown effect '{effect}'")


def _hero_damage_line(hero: dict, spell: dict) -> str:
    name = hero.get("name", hero["id"])
    line = f"{name} takes {spell['damage']} Body Points of damage."
    if spell.get("reductionDice"):
        line += (
            f" Roll {spell['reductionDice']} red dice -- each 5 or 6 takes one point back. "
            f"Apply what's left on the hero sheet."
        )
    return line


def _resolve_bolt(board, quest, game_state, heroes, caster_pos, spell, result) -> ChaosSpellResult:
    hero_squares = {tuple(h["pos"]): h for h in heroes}
    monsters = {
        mid: m for mid, m in game_state.get("monsters", {}).items() if m.get("alive")
    }
    monster_squares = {tuple(m["pos"]): mid for mid, m in monsters.items()}

    best_dir, best_path, best_score = None, [], (-1, 0)
    for direction in _BOLT_DIRECTIONS:
        path = _bolt_path(board, quest, game_state, caster_pos, direction)
        heroes_hit = sum(1 for sq in path if sq in hero_squares)
        monsters_hit = sum(1 for sq in path if sq in monster_squares)
        # Most heroes wins; among equals, spare Zargon's own.
        score = (heroes_hit, -monsters_hit)
        if score > best_score:
            best_dir, best_path, best_score = direction, path, score

    if best_dir is None or best_score[0] <= 0:
        raise ChaosSpellUnavailableError("no line catches a hero")

    result.log.append(
        f"The bolt runs {_direction_name(best_dir)} from [{caster_pos[0]},{caster_pos[1]}] "
        f"to [{best_path[-1][0]},{best_path[-1][1]}]."
    )
    for square in best_path:
        hero = hero_squares.get(square)
        if hero is not None:
            result.hero_hits.append(HeroHit(hero["id"], hero.get("name", hero["id"]), spell["damage"]))
            result.log.append(_hero_damage_line(hero, spell))
        mid = monster_squares.get(square)
        if mid is not None:
            result.monster_damage[mid] = result.monster_damage.get(mid, 0) + spell["damage"]
            result.log.append(f"The bolt also catches {mid} -- {spell['damage']} Body Points.")
    return result


def _direction_name(direction) -> str:
    names = {
        (1, 0): "east", (-1, 0): "west", (0, 1): "south", (0, -1): "north",
        (1, 1): "south-east", (1, -1): "north-east", (-1, 1): "south-west", (-1, -1): "north-west",
    }
    return names.get(direction, "outward")


def _resolve_firestorm(board, catalogs, quest, game_state, heroes, caster_id, caster_pos, spell, result, rng):
    area = board.area_of.get(caster_pos)
    if spell.get("roomsOnly") and area == CORRIDOR:
        raise ChaosSpellUnavailableError("Firestorm is not used in corridors")

    for hero in heroes:
        if board.area_of.get(tuple(hero["pos"])) != area:
            continue
        result.hero_hits.append(
            HeroHit(hero["id"], hero.get("name", hero["id"]), spell["damage"], spell.get("reductionDice", 0))
        )
        result.log.append(_hero_damage_line(hero, spell))

    for mid, monster in game_state.get("monsters", {}).items():
        if not monster.get("alive") or mid == caster_id:
            continue
        if board.area_of.get(tuple(monster["pos"])) != area:
            continue
        # Zargon's own victims roll Zargon's dice, so the app rolls these.
        saved = sum(1 for _ in range(spell.get("reductionDice", 0)) if rng.randint(1, 6) >= 5)
        damage = max(0, spell["damage"] - saved)
        if damage:
            result.monster_damage[mid] = result.monster_damage.get(mid, 0) + damage
        result.log.append(f"The fire catches {mid} too -- {damage} Body Points after its own dice.")

    if not result.hero_hits:
        raise ChaosSpellUnavailableError("no hero in the room to burn")
    return result


def _resolve_status(board, quest, game_state, heroes, caster_pos, spell, result) -> ChaosSpellResult:
    status = spell["status"]
    if spell["target"] == "all_heroes_in_area":
        area = board.area_of.get(caster_pos)
        victims = [h for h in heroes if board.area_of.get(tuple(h["pos"])) == area]
    else:
        victims = visible_heroes(board, quest, game_state, heroes, caster_pos)[:1]

    if not victims:
        raise ChaosSpellUnavailableError("no hero in sight to target")

    for hero in victims:
        result.statuses.append(
            {
                "heroId": hero["id"],
                "heroName": hero.get("name", hero["id"]),
                "status": status,
                "missesTurns": spell.get("missesTurns", 0),
            }
        )
        result.log.append(_status_line(hero.get("name", hero["id"]), status, spell))
    return result


def _status_line(hero_name: str, status: str, spell: dict) -> str:
    if status == "becalmed":
        return f"{hero_name} is caught in the whirlwind and misses their next turn."
    if status == "afraid":
        return f"{hero_name} is gripped by fear -- their attacks are one combat die until it breaks."
    if status == "commanded":
        return f"{hero_name} is under Zargon's command. Zargon moves them now, not you."
    verb = "asleep" if status == "asleep" else "paralyzed"
    return (
        f"{hero_name} is {verb} -- no moving, attacking or defending. "
        f"Roll one red die per Mind Point to break it"
        f"{' (from next turn)' if not spell.get('breakImmediately', True) else ''}."
    )


def _resolve_summon(board, catalogs, game_state, heroes, caster_pos, spell, result, rng) -> ChaosSpellResult:
    roll = rng.randint(1, 6)
    entry = next((row for row in spell["table"] if roll in row["rolls"]), None)
    if entry is None:  # pragma: no cover -- the tables cover 1-6
        raise ChaosSpellUnavailableError("the summon table has a gap")

    result.log.append(f"Zargon rolls a {roll} on one red die.")
    occupied = {tuple(h["pos"]) for h in heroes} | {
        tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")
    }

    for monster_type, wanted in entry["monsters"].items():
        # Minis are physical and don't multiply: the summon can only put
        # down what is actually free (CLAUDE.md's per-type owned counts).
        catalog_entry = catalogs.monsters.get(monster_type)
        owned = catalog_entry.get("roomCap") if catalog_entry else None
        in_play = sum(
            1
            for m in game_state.get("monsters", {}).values()
            if m.get("alive") and m.get("type") == monster_type
        )
        free_minis = wanted if owned is None else max(0, owned - in_play)
        squares = _free_squares_near(board, caster_pos, occupied, wanted)
        placed = min(wanted, len(squares), free_minis)

        for square in squares[:placed]:
            occupied.add(square)
            result.summons.append({"type": monster_type, "pos": square})
        if placed:
            where = ", ".join(f"[{sq[0]},{sq[1]}]" for sq in squares[:placed])
            instruction = f"Place {placed} {monster_type}(s) at {where}."
            result.placement_instructions.append(instruction)
            result.log.append(instruction)
        if placed < wanted:
            short = wanted - placed
            reason = "no free square" if len(squares) < wanted else f"only {free_minis} {monster_type} mini(s) free"
            result.log.append(
                f"{short} more {monster_type}(s) were called but there is {reason} -- "
                f"proxy them or leave them out, Zargon's call."
            )
    return result


# Which card to spend, when a caster has more than one. Ordered by how
# much of the party it can take out of the fight at once: a room-wide
# card beats a single-target one, and the survival card (Escape) is a
# last resort rather than an opener.
CAST_PRIORITY = (
    "firestorm",
    "cloud_of_chaos",
    "lightning_bolt",
    "summon_undead",
    "summon_orcs",
    "command",
    "sleep",
    "ball_of_flame",
    "tempest",
    "fear",
    "rust",
    "escape",
)


def choose_spell(
    *,
    board: Board,
    quest: dict,
    game_state: dict,
    heroes: list[dict],
    caster_pos: Coord,
    available: list[str],
) -> str | None:
    """Which spell a caster uses this turn, or None to fight normally.

    The card's own condition first: "a monster can only cast a spell on
    a Hero that it can see". After that it is a fixed order of
    preference (CAST_PRIORITY) with two situational rules -- a room-wide
    card is only worth spending when it catches more than one hero, and
    Escape only when the caster is about to die.
    """
    unspent = [s for s in available if s not in set(game_state.get("chaosSpellsCast", []))]
    if not unspent:
        return None

    seen = visible_heroes(board, quest, game_state, heroes, caster_pos)
    if not seen:
        return None

    area = board.area_of.get(caster_pos)
    heroes_in_area = sum(1 for h in heroes if board.area_of.get(tuple(h["pos"])) == area)

    for spell_id in CAST_PRIORITY:
        if spell_id not in unspent:
            continue
        spell = CHAOS_SPELLS[spell_id]
        if spell.get("roomsOnly") and area == CORRIDOR:
            continue
        if spell["target"] in ("casters_room", "all_heroes_in_area"):
            if heroes_in_area < 2:
                continue  # save the big card for a crowd
        if spell_id == "escape":
            continue  # handled by the caller, which knows the caster's wounds
        return spell_id
    return None
