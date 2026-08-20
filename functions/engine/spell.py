"""Resolves the hero "cast a spell" action (1989 rulebook, Action 2).

    "As the Elf or the Wizard, you may cast a spell instead of
    attacking. You may cast a spell at anything you can 'see'.
    Important: You may only cast a spell on your turn. [...] Once a
    spell is cast, the spell card is discarded for the remainder of the
    Quest. Each spell may be cast only once per Quest."

Spell CARDS are physical (CLAUDE.md's boundary) -- the app has no
catalogue of them and never learns what a spell does. What it can
enforce is everything around the card:

- only the Elf and the Wizard cast at all;
- the target must be visible by the rulebook's own "SEE" rule, which
  engine/line_of_sight.py now implements exactly;
- a given spell is spent once per quest.

Effects split along the same boundary as combat. A spell aimed at a
MONSTER lands on digital state, so the hero reports the skulls their
card called for and the engine applies damage -- identical to the
attack flow, except the caster needs sight rather than adjacency, and
some cards allow no defence roll at all (monster_defends=False).
Anything aimed at a hero (healing, buffs) touches only physical state,
so the app logs the cast, spends the card, and changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from validator.catalogs import Board, Catalogs

from .combat import MonsterDefenseResult, resolve_hero_attack
from .heroes import find_living_hero, living_heroes
from .line_of_sight import has_line_of_sight
from .movement import passable_door_edges

Coord = tuple[int, int]

# The two heroes with spell cards. The Wizard takes three spell groups
# and the Elf one (rulebook, Dividing The Spells).
CASTER_HERO_IDS = frozenset({"elf", "wizard"})


class InvalidSpellError(ValueError):
    """The cast can't happen: the hero isn't a caster, the spell is
    already spent this quest, or the target isn't visible.
    """


@dataclass
class SpellResult:
    hero_id: str
    spell_name: str
    target_monster_id: str | None = None
    defense: MonsterDefenseResult | None = None
    log: list[str] = field(default_factory=list)


def resolve_hero_spell(
    *,
    board: Board,
    catalogs: Catalogs,
    quest: dict,
    game_state: dict,
    hero_id: str,
    spell_name: str,
    target_monster_id: str | None = None,
    skulls: int = 0,
    monster_defends: bool = True,
    rng=None,
) -> SpellResult:
    if hero_id not in CASTER_HERO_IDS:
        raise InvalidSpellError(f"'{hero_id}' has no spells -- only the Elf and the Wizard cast")

    spell_name = (spell_name or "").strip()
    if not spell_name:
        raise InvalidSpellError("name the spell being cast (it's on the physical card)")

    already_cast = {s.lower() for s in game_state.get("spellsCast", [])}
    if spell_name.lower() in already_cast:
        raise InvalidSpellError(f"'{spell_name}' has already been cast this quest -- the card is discarded")

    heroes = living_heroes(game_state)
    hero = find_living_hero(game_state, hero_id)
    if hero is None:
        raise InvalidSpellError(f"hero '{hero_id}' is not in this game, or has fallen")
    hero_pos = tuple(hero["pos"])
    hero_name = hero.get("name", hero_id)

    if target_monster_id is None:
        # Aimed at a hero, or at nothing in particular. The card's effect
        # is physical, so the app only records that it was spent.
        return SpellResult(
            hero_id=hero_id,
            spell_name=spell_name,
            log=[f"{hero_name} casts {spell_name}. Apply the card's effect at the table; the card is now discarded."],
        )

    monster = game_state.get("monsters", {}).get(target_monster_id)
    if monster is None or not monster.get("alive"):
        raise InvalidSpellError(f"monster '{target_monster_id}' isn't in play")

    monster_pos = tuple(monster["pos"])
    open_edges = passable_door_edges(quest.get("doors", []), game_state.get("doors", {}))
    walls = frozenset(
        {tuple(sq) for sq in quest.get("blockedSquares", [])}
        | {tuple(sq) for sq in game_state.get("collapsedSquares", [])}
    )
    figures = frozenset(
        {tuple(h["pos"]) for h in heroes}
        | {tuple(m["pos"]) for m in game_state.get("monsters", {}).values() if m.get("alive")}
    )
    if not has_line_of_sight(
        board, hero_pos, monster_pos, open_door_edges=open_edges, walls=walls, figures=figures
    ):
        raise InvalidSpellError(f"{hero_name} can't see that target -- a spell needs a clear line of sight")

    monster_type = monster.get("type", "monster")
    catalog_entry = catalogs.monsters.get(monster_type, {})
    defend_dice = catalog_entry.get("defend", 0) if monster_defends else 0

    defense = resolve_hero_attack(
        monster_name=monster_type,
        monster_defend_dice=defend_dice,
        skulls=skulls,
        current_body=monster.get("currentBody", 1),
        rng=rng,
    )

    log = [f"{hero_name} casts {spell_name} at the {monster_type}."]
    if not monster_defends:
        log.append("The spell allows no defence roll.")
    log.append(defense.log)

    return SpellResult(
        hero_id=hero_id,
        spell_name=spell_name,
        target_monster_id=target_monster_id,
        defense=defense,
        log=log,
    )
