"""The four 1989 hero cards, as the simulator needs them.

Body Points are physical in the real app (CLAUDE.md's boundary) -- the
sim has to track them itself, which is the main thing that makes this a
model of play rather than play itself.

Movement is 2d6 per turn, the same red dice the player rolls at the
table. Equipment, treasure, spells and potions are NOT modelled: every
hero fights with their starting weapon for the whole quest. That makes
the sim pessimistic in absolute terms -- which is fine, because it is
used to compare two rule sets against each other, not to predict a real
party's win rate (see README.md).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HeroCard:
    id: str
    name: str
    body: int
    attack_dice: int
    defend_dice: int
    # Mind Points matter for exactly one thing here: shaking off a Chaos
    # spell is one red die per Mind Point, breaking on a 6.
    mind: int


HERO_CARDS = {
    "barbarian": HeroCard("barbarian", "Barbarian", body=8, attack_dice=3, defend_dice=2, mind=2),
    "dwarf": HeroCard("dwarf", "Dwarf", body=7, attack_dice=2, defend_dice=2, mind=3),
    "elf": HeroCard("elf", "Elf", body=6, attack_dice=2, defend_dice=2, mind=4),
    "wizard": HeroCard("wizard", "Wizard", body=4, attack_dice=1, defend_dice=2, mind=6),
}

# Party composition by size, strongest first -- a solo player picking one
# hero picks the Barbarian far more often than the Wizard.
PARTY_ORDER = ("barbarian", "dwarf", "elf", "wizard")


def party_for(hero_count: int) -> list[HeroCard]:
    return [HERO_CARDS[hid] for hid in PARTY_ORDER[:hero_count]]
