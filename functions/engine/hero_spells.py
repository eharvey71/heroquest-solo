"""The twelve base-game hero spell cards.

Card text is transcribed verbatim from the owner's 1989 cards into
data/hero_spells.json; this module resolves them. The Elf and Wizard
cast INSTEAD of attacking, at any target they can SEE (engine/
line_of_sight.py), once per card per quest.

Which cards a hero is even holding is decided at game creation: the
Wizard takes three elements and the Elf one, and those choices live in
game state's `spellbooks` (see engine/create_game.py). A hero can only
cast from their own elements.

The physical/digital line runs through the deck, as it does through
Zargon's:

- The app OWNS what it can see. Damage to monsters, and the monster's
  own save roll ("rolls two red dice, each 5 or 6 reduces it"), because
  those are Zargon's dice. Sleep and Tempest, because a held monster is
  enforced by Zargon skipping its turn -- and a sleeping one rolls no
  defend dice at all. The Genie opening any door on the board. Veil of
  Mist and Pass Through Rock, because the app validates movement and
  these change what a legal path is.
- The app ANNOUNCES what it can't. Body Points restored (Heal Body,
  Water of Healing), extra hero dice (Rock Skin, Courage), and the
  doubled movement roll (Swift Wind) are all the player's own sheet and
  the player's own dice.

Pass Through Rock's "trapped forever in solid rock" has no equivalent
here: every square on this board is room or corridor, so there is no
shaded area to be stranded in. Walls simply stop blocking for one move.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from validator.catalogs import Board, Catalogs

from .line_of_sight import has_line_of_sight
from .movement import passable_door_edges

Coord = tuple[int, int]

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "hero_spells.json"

CASTER_HERO_IDS = frozenset({"elf", "wizard"})

# The Wizard takes three, the Elf one of what's left.
WIZARD_ELEMENT_COUNT = 3
ELF_ELEMENT_COUNT = 1


class UnknownHeroSpellError(ValueError):
    """No such card."""


class HeroSpellUnavailableError(ValueError):
    """Already cast, not in this hero's spellbook, or an illegal target."""


@dataclass
class HeroSpellResult:
    spell_id: str
    spell_name: str
    caster_id: str
    monster_damage: dict = field(default_factory=dict)  # monsterId -> body points
    monster_statuses: list = field(default_factory=list)  # {monsterId, status, missesTurns}
    hero_statuses: list = field(default_factory=list)  # {heroId, status, consumedByMove, playerCleared}
    opened_door_id: str | None = None
    log: list[str] = field(default_factory=list)


def load_hero_spells(path: Path | None = None) -> dict:
    return json.loads((path or DATA_PATH).read_text())


HERO_SPELLS = load_hero_spells()

ELEMENTS = tuple(sorted({spell["element"] for spell in HERO_SPELLS.values()}))


def spells_in_elements(elements) -> list[str]:
    wanted = {e.lower() for e in elements or ()}
    return sorted(sid for sid, spell in HERO_SPELLS.items() if spell["element"].lower() in wanted)


def spellbook_for(game_state: dict, hero_id: str) -> list[str]:
    """The cards this hero is actually holding."""
    elements = (game_state.get("spellbooks") or {}).get(hero_id) or []
    return spells_in_elements(elements)


def validate_spellbooks(spellbooks: dict) -> None:
    """The Wizard takes three elements, the Elf one, and no element is in
    two hands at once -- each element is one physical set of three cards.
    """
    known = {e.lower() for e in ELEMENTS}
    seen: set[str] = set()
    for hero_id, elements in (spellbooks or {}).items():
        if hero_id not in CASTER_HERO_IDS:
            raise HeroSpellUnavailableError(f"'{hero_id}' is not a spellcaster")
        picked = [e.lower() for e in elements or []]
        if len(set(picked)) != len(picked):
            raise HeroSpellUnavailableError(f"{hero_id} was given the same element twice")
        unknown = set(picked) - known
        if unknown:
            raise HeroSpellUnavailableError(f"unknown spell element(s): {sorted(unknown)}")
        expected = WIZARD_ELEMENT_COUNT if hero_id == "wizard" else ELF_ELEMENT_COUNT
        if len(picked) != expected:
            raise HeroSpellUnavailableError(
                f"the {hero_id} takes {expected} element(s), got {len(picked)}"
            )
        clash = seen & set(picked)
        if clash:
            raise HeroSpellUnavailableError(f"element(s) {sorted(clash)} were given to two heroes")
        seen |= set(picked)


def _can_see(board, quest, game_state, heroes, origin: Coord, target: Coord) -> bool:
    open_edges = passable_door_edges(quest.get("doors", []), game_state.get("doors", {}))
    walls = frozenset(
        {tuple(sq) for sq in quest.get("blockedSquares", [])}
        | {tuple(sq) for sq in game_state.get("collapsedSquares", [])}
    )
    figures = frozenset(
        {tuple(h["pos"]) for h in heroes} | {
            tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")
        }
    ) - {origin, target}
    return has_line_of_sight(board, origin, target, open_door_edges=open_edges, walls=walls, figures=figures)


def resolve_hero_spell(
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
    target_monster_id: str | None = None,
    target_hero_id: str | None = None,
    door_id: str | None = None,
    genie_mode: str | None = None,
    rng: random.Random | None = None,
) -> HeroSpellResult:
    rng = rng or random
    spell = HERO_SPELLS.get(spell_id)
    if spell is None:
        raise UnknownHeroSpellError(f"no hero spell '{spell_id}'")
    if caster_id not in CASTER_HERO_IDS:
        raise HeroSpellUnavailableError(f"'{caster_id}' holds no spell cards")
    if spell_id not in spellbook_for(game_state, caster_id):
        raise HeroSpellUnavailableError(f"{caster_name} is not holding {spell['name']}")
    if spell_id in set(game_state.get("spellsCast", [])):
        raise HeroSpellUnavailableError(f"{spell['name']} has already been cast this quest")

    result = HeroSpellResult(spell_id=spell_id, spell_name=spell["name"], caster_id=caster_id)
    result.log.append(f"{caster_name} casts {spell['name']}. {spell['text']}")
    effect = spell["effect"]

    if effect == "narrate_hero" or (effect == "hero_status"):
        hero = next((h for h in heroes if h["id"] == (target_hero_id or caster_id)), None)
        if hero is None:
            raise HeroSpellUnavailableError("that hero isn't in play")
        name = hero.get("name", hero["id"])
        if effect == "narrate_hero":
            result.log.append(f"{name}: {spell['prompt']}")
            return result
        result.hero_statuses.append(
            {
                "heroId": hero["id"],
                "status": spell["status"],
                "consumedByMove": bool(spell.get("consumedByMove")),
                "playerCleared": bool(spell.get("playerCleared")),
            }
        )
        result.log.append(f"{name}: {spell.get('prompt') or _status_prompt(spell['status'])}")
        return result

    if effect in ("damage_monster", "monster_status"):
        monster = game_state.get("monsters", {}).get(target_monster_id or "")
        if monster is None or not monster.get("alive"):
            raise HeroSpellUnavailableError("that monster isn't in play")
        monster_pos = tuple(monster["pos"])
        if not _can_see(board, quest, game_state, heroes, caster_pos, monster_pos):
            raise HeroSpellUnavailableError(f"{caster_name} can't see that monster")

        monster_name = _monster_name(quest, target_monster_id, monster)

        if effect == "monster_status":
            excluded = {t.lower() for t in spell.get("excludedTypes", [])}
            if monster.get("type", "").lower() in excluded:
                raise HeroSpellUnavailableError(
                    f"{spell['name']} has no hold over a {monster.get('type')}"
                )
            result.monster_statuses.append(
                {
                    "monsterId": target_monster_id,
                    "status": spell["status"],
                    "missesTurns": spell.get("missesTurns", 0),
                }
            )
            result.log.append(_monster_status_line(monster_name, spell))
            return result

        # damage_monster: the save is the MONSTER's roll, so the app makes it.
        saved = sum(1 for _ in range(spell.get("saveDice", 0)) if rng.randint(1, 6) >= spell.get("saveOn", 5))
        if spell.get("saveNegatesAll"):
            damage = 0 if saved else spell["damage"]
            rolled = f"rolls {saved and 'a 5 or 6 and shrugs it off' or 'no save'}"
        else:
            damage = max(0, spell["damage"] - saved)
            rolled = f"saves {saved} of it on {spell.get('saveDice', 0)} red dice"
        result.monster_damage[target_monster_id] = damage
        result.log.append(f"{monster_name} {rolled}: {damage} Body Point(s) of damage.")
        return result

    if effect == "genie":
        if genie_mode == "door":
            if not door_id:
                raise HeroSpellUnavailableError("name the door for the Genie to open")
            # "Open any door ON THE BOARD" -- the doors on the board are
            # the ones that have been placed, i.e. found. A door in a
            # room nobody has opened yet isn't on the table to point at,
            # and offering it would hand the player the map.
            door = next((d for d in quest.get("doors", []) if d.get("id") == door_id), None)
            if door is None:
                raise HeroSpellUnavailableError(f"no door '{door_id}' in this quest")
            if not _door_is_on_the_board(board, door, game_state):
                raise HeroSpellUnavailableError(
                    f"door '{door_id}' hasn't been found yet -- the Genie can only open a door on the board"
                )
            result.opened_door_id = door_id
            result.log.append(
                f"The Genie throws open door {door_id} -- anywhere on the board, seen or not."
            )
            return result
        monster = game_state.get("monsters", {}).get(target_monster_id or "")
        if monster is None or not monster.get("alive"):
            raise HeroSpellUnavailableError("that monster isn't in play")
        if not _can_see(board, quest, game_state, heroes, caster_pos, tuple(monster["pos"])):
            raise HeroSpellUnavailableError(f"{caster_name} can't see that monster")
        # The Genie's own five dice, not the hero's, so the app rolls the
        # attack AND the monster's defence -- both are Zargon-side dice.
        from .combat import resolve_hero_attack
        from .dice import roll_attack

        monster_name = _monster_name(quest, target_monster_id, monster)
        attack = resolve_hero_attack(
            monster_name=monster_name,
            monster_defend_dice=_defend_dice(quest, catalogs, target_monster_id, monster, game_state),
            skulls=roll_attack(spell.get("attackDice", 5), rng),
            current_body=monster["currentBody"],
            rng=rng,
        )
        result.monster_damage[target_monster_id] = attack.damage
        result.log.append(f"The Genie strikes with {spell.get('attackDice', 5)} combat dice. {attack.log}")
        return result

    raise UnknownHeroSpellError(f"hero spell '{spell_id}' has an unknown effect '{effect}'")


def _door_is_on_the_board(board: Board, door: dict, game_state: dict) -> bool:
    """A door is physically on the table once one of its squares has
    been revealed and it isn't still a secret. Same rule the renderer
    uses to decide whether to draw it (web BoardTerrain).
    """
    if door.get("state") == "secret" and game_state.get("doors", {}).get(door["id"]) is None:
        return False
    if game_state.get("doors", {}).get(door["id"]) == "secret":
        return False
    revealed_rooms = set(game_state.get("revealed", {}).get("rooms", []))
    revealed_corridor = {tuple(sq) for sq in game_state.get("revealed", {}).get("corridorSquares", [])}
    for square in door.get("squares", []):
        square = tuple(square)
        area = board.area_of.get(square)
        if area in revealed_rooms or square in revealed_corridor:
            return True
    return False


def _status_prompt(status: str) -> str:
    if status == "veiled":
        return "the next move may pass straight through monsters."
    if status == "through_rock":
        return "the next move may pass straight through walls."
    return "the spell takes hold."


def _monster_status_line(monster_name: str, spell: dict) -> str:
    if spell["status"] == "becalmed":
        return f"{monster_name} is caught in the whirlwind and misses its next turn."
    return (
        f"{monster_name} falls asleep -- it cannot move, attack, or even defend itself. "
        f"Zargon rolls one red die per Mind Point each turn to wake it."
    )


def _defend_dice(quest: dict, catalogs, monster_id: str | None, monster: dict, game_state: dict) -> int:
    """The monster's defend dice -- zero if it is asleep, since a
    sleeping monster "cannot ... defend itself"."""
    from .monster_status import defend_dice_for

    dice = catalogs.monsters.get(monster.get("type"), {}).get("defend", 0)
    for room in quest.get("rooms", {}).values():
        for m in room.get("monsters", []):
            if m.get("id") == monster_id:
                dice = m.get("overrides", {}).get("defend", dice)
    return defend_dice_for(game_state, monster_id or "", dice)


def _monster_name(quest: dict, monster_id: str | None, monster: dict) -> str:
    for room in quest.get("rooms", {}).values():
        for m in room.get("monsters", []):
            if m.get("id") == monster_id:
                return m.get("name") or m.get("type", monster_id or "the monster")
    return monster.get("type", monster_id or "the monster")
