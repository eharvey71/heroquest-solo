import random

from engine.dice import (
    count_hero_blocks,
    count_monster_blocks,
    count_skulls,
    roll_attack,
    roll_dice,
    roll_hero_defend,
    roll_monster_defend,
)

N = 60_000
TOLERANCE = 0.02  # generous for a seeded-but-random sample


def test_face_ratio_is_three_skull_two_white_one_black():
    faces = roll_dice(N, random.Random(1))
    skulls = sum(1 for f in faces if f == "skull")
    white = sum(1 for f in faces if f == "white_shield")
    black = sum(1 for f in faces if f == "black_shield")
    assert skulls + white + black == N
    assert abs(skulls / N - 3 / 6) < TOLERANCE
    assert abs(white / N - 2 / 6) < TOLERANCE
    assert abs(black / N - 1 / 6) < TOLERANCE


def test_roll_attack_rate_matches_skull_probability():
    rng = random.Random(2)
    skulls = sum(roll_attack(1, rng) for _ in range(N))
    assert abs(skulls / N - 0.5) < TOLERANCE


def test_roll_monster_defend_only_counts_black_shield():
    rng = random.Random(3)
    blocks = sum(roll_monster_defend(1, rng) for _ in range(N))
    assert abs(blocks / N - 1 / 6) < TOLERANCE


def test_roll_hero_defend_only_counts_white_shield():
    rng = random.Random(4)
    blocks = sum(roll_hero_defend(1, rng) for _ in range(N))
    assert abs(blocks / N - 2 / 6) < TOLERANCE


def test_white_and_black_shields_are_not_interchangeable():
    # A face that blocks for a hero must never also count as a monster
    # block, and vice versa -- this is the whole point of the asymmetric
    # die (confirmed against the physical die, not assumed).
    faces = roll_dice(1000, random.Random(5))
    black_shield_faces = [f for f in faces if f == "black_shield"]
    assert count_hero_blocks(black_shield_faces) == 0
    white_shield_faces = [f for f in faces if f == "white_shield"]
    assert count_monster_blocks(white_shield_faces) == 0


def test_deterministic_with_seeded_rng():
    a = roll_dice(20, random.Random(42))
    b = roll_dice(20, random.Random(42))
    assert a == b


def test_count_skulls_ignores_shields():
    faces = ["skull", "white_shield", "black_shield", "skull"]
    assert count_skulls(faces) == 2
