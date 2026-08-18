import random

from engine.combat import record_hero_defense, resolve_hero_attack, roll_monster_attack


def test_hero_attack_applies_net_damage_to_monster():
    # rng seeded so we know exactly what the monster's defend roll produces.
    rng = random.Random(1)
    result = resolve_hero_attack(
        monster_name="Orc", monster_defend_dice=2, skulls=3, current_body=2, rng=rng
    )
    assert result.damage == result.skulls_faced - result.blocks
    assert result.body_points_after == max(0, 2 - result.damage)


def test_hero_attack_cannot_reduce_body_below_zero():
    rng = random.Random(2)
    result = resolve_hero_attack(
        monster_name="Goblin", monster_defend_dice=0, skulls=99, current_body=1, rng=rng
    )
    assert result.body_points_after == 0
    assert result.defeated is True


def test_hero_attack_no_damage_if_fully_blocked():
    # 0 defend dice always yields 0 blocks -- skulls must equal blocks
    # only when skulls is also 0.
    rng = random.Random(3)
    result = resolve_hero_attack(
        monster_name="Skeleton", monster_defend_dice=0, skulls=0, current_body=1, rng=rng
    )
    assert result.damage == 0
    assert result.body_points_after == 1
    assert result.defeated is False


def test_monster_attack_reports_skulls_and_prompts_hero():
    rng = random.Random(4)
    attack = roll_monster_attack(monster_name="Gargoyle", hero_name="Wizard", attack_dice=4, rng=rng)
    assert attack.dice_rolled == 4
    assert 0 <= attack.skulls <= 4
    assert "Wizard" in attack.log
    assert "roll your defend dice" in attack.log


def test_record_hero_defense_never_touches_body_points():
    rng = random.Random(5)
    attack = roll_monster_attack(monster_name="Orc", hero_name="Barbarian", attack_dice=3, rng=rng)
    log_line = record_hero_defense(hero_name="Barbarian", skulls_faced=attack.skulls, shields_reported=1)
    # Log-only: no return value beyond the narration string, and the
    # wording makes clear the wound is tracked on the physical sheet.
    assert isinstance(log_line, str)
    assert "tracked on hero sheet" in log_line


def test_record_hero_defense_wounds_never_negative():
    # Over-reporting shields (more than skulls rolled) must not go negative.
    log_line = record_hero_defense(hero_name="Wizard", skulls_faced=1, shields_reported=99)
    assert "-> 0 wound(s)" in log_line


def test_deterministic_with_seeded_rng():
    a = resolve_hero_attack(monster_name="Orc", monster_defend_dice=3, skulls=2, current_body=3, rng=random.Random(42))
    b = resolve_hero_attack(monster_name="Orc", monster_defend_dice=3, skulls=2, current_body=3, rng=random.Random(42))
    assert a == b
