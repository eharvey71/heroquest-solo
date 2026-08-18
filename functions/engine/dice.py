"""The 1989 NA HeroQuest combat die and rolling helpers.

Confirmed against the owner's physical die (not assumed): six faces —
3 skull, 2 white shield, 1 black shield. Skull is a hit for whichever
side is attacking. The shields are NOT interchangeable: white shield
only blocks for a defending HERO, black shield only blocks for a
defending MONSTER. This is why monsters lean on higher defend-dice
*counts* in monsters.json rather than good per-die odds — a gargoyle's
defend 5 compensates for only a 1-in-6 block chance per die, versus a
hero's 2-in-6.

"Zargon's dice rolls" are digital (CLAUDE.md) — this module is only
ever used for the monster's own rolls (attacking, or defending against
a hero's reported skulls). A hero's own attack/defend dice are physical;
this module never rolls on a hero's behalf in the real flow, but
roll_hero_defend exists for completeness/tests.
"""

from __future__ import annotations

import random

DIE_SKULL = "skull"
DIE_WHITE_SHIELD = "white_shield"
DIE_BLACK_SHIELD = "black_shield"

# 3 skull, 2 white shield, 1 black shield -- order doesn't matter, only the ratio.
DIE_FACES = (
    DIE_SKULL,
    DIE_SKULL,
    DIE_SKULL,
    DIE_WHITE_SHIELD,
    DIE_WHITE_SHIELD,
    DIE_BLACK_SHIELD,
)


def roll_dice(count: int, rng: random.Random | None = None) -> list[str]:
    """Rolls `count` combat dice, returns the raw face results."""
    rng = rng or random
    return [rng.choice(DIE_FACES) for _ in range(count)]


def count_skulls(faces: list[str]) -> int:
    return sum(1 for f in faces if f == DIE_SKULL)


def count_hero_blocks(faces: list[str]) -> int:
    """White shields only -- for a defending hero."""
    return sum(1 for f in faces if f == DIE_WHITE_SHIELD)


def count_monster_blocks(faces: list[str]) -> int:
    """Black shields only -- for a defending monster."""
    return sum(1 for f in faces if f == DIE_BLACK_SHIELD)


def roll_attack(count: int, rng: random.Random | None = None) -> int:
    """Rolls `count` attack dice, returns the skull (hit) count."""
    return count_skulls(roll_dice(count, rng))


def roll_monster_defend(count: int, rng: random.Random | None = None) -> int:
    """Rolls `count` defend dice for a MONSTER, returns black-shield block count."""
    return count_monster_blocks(roll_dice(count, rng))


def roll_hero_defend(count: int, rng: random.Random | None = None) -> int:
    """Rolls `count` defend dice for a HERO, returns white-shield block count.

    Not used in the real flow (heroes roll their own physical dice) --
    kept for symmetry and tests of the die model itself.
    """
    return count_hero_blocks(roll_dice(count, rng))
