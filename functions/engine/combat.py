"""Combat resolution. Two directions, deliberately asymmetric in what
gets tracked, per the settled physical/digital boundary (CLAUDE.md):

- Hero attacks monster: hero rolls attack dice physically and reports
  the skull count (the only thing the engine needs from them). The
  engine then rolls the monster's defend dice itself -- "Zargon's dice
  rolls" are digital -- and applies the resulting damage to the
  monster's body points, since that IS digital state.
- Monster attacks hero: the engine rolls the monster's attack dice
  itself and reports the skull count. The hero then defends with their
  own physical dice and *may* report shields back, but purely so the
  turn log has a complete narration line -- hero body points are never
  computed, stored, or touched here. That's the owner's physical hero
  sheet, permanently out of scope for this app.

Every function here takes and returns plain values/dataclasses, not
Firestore documents -- callers (functions/engine/turn.py, and later a
Cloud Function) own persistence.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .dice import roll_attack, roll_monster_defend


@dataclass
class MonsterAttackRoll:
    monster_name: str
    hero_name: str
    dice_rolled: int
    skulls: int
    log: str


@dataclass
class MonsterDefenseResult:
    monster_name: str
    dice_rolled: int
    blocks: int
    skulls_faced: int
    damage: int
    body_points_before: int
    body_points_after: int
    defeated: bool
    log: str


def resolve_hero_attack(
    *,
    monster_name: str,
    monster_defend_dice: int,
    skulls: int,
    current_body: int,
    rng: random.Random | None = None,
) -> MonsterDefenseResult:
    """Hero has already rolled physically and reported `skulls`. Rolls
    the monster's defend dice digitally and applies net damage.
    """
    blocks = roll_monster_defend(monster_defend_dice, rng)
    damage = max(0, skulls - blocks)
    body_after = max(0, current_body - damage)
    defeated = body_after <= 0

    log = (
        f"{monster_name} defends: {monster_defend_dice} dice, {blocks} block(s) "
        f"vs {skulls} skull(s) -> {damage} wound(s). "
        f"{monster_name} at {body_after}/{current_body} body points."
        + (f" {monster_name} is defeated!" if defeated else "")
    )

    return MonsterDefenseResult(
        monster_name=monster_name,
        dice_rolled=monster_defend_dice,
        blocks=blocks,
        skulls_faced=skulls,
        damage=damage,
        body_points_before=current_body,
        body_points_after=body_after,
        defeated=defeated,
        log=log,
    )


def roll_monster_attack(
    *,
    monster_name: str,
    hero_name: str,
    attack_dice: int,
    rng: random.Random | None = None,
) -> MonsterAttackRoll:
    """Rolls the monster's attack dice digitally. The hero defends with
    their own physical dice next -- see record_hero_defense.
    """
    skulls = roll_attack(attack_dice, rng)
    log = (
        f"{monster_name} attacks {hero_name}: {attack_dice} dice, {skulls} skull(s). "
        f"{hero_name}, roll your defend dice."
    )
    return MonsterAttackRoll(
        monster_name=monster_name,
        hero_name=hero_name,
        dice_rolled=attack_dice,
        skulls=skulls,
        log=log,
    )


def record_hero_defense(*, hero_name: str, attack: MonsterAttackRoll, shields_reported: int) -> str:
    """Log-only: completes the turn narration with what the hero rolled.
    Never computes or stores hero body points -- that's the physical
    hero sheet's job, not this app's.
    """
    wounds = max(0, attack.skulls - shields_reported)
    return (
        f"{hero_name} defends: {shields_reported} shield(s) vs {attack.skulls} skull(s) "
        f"-> {wounds} wound(s) (tracked on hero sheet)."
    )
