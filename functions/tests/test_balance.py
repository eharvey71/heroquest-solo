import pytest

from validator.balance import caster_types, check_balance


def test_budget_too_low_rejected(good_quest_4h, good_quest_4h_params, catalogs):
    for room in good_quest_4h["rooms"].values():
        room["monsters"] = []
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("monster budget is 0" in e for e in errors)


def test_budget_too_high_rejected(good_quest_4h, good_quest_4h_params, catalogs):
    good_quest_4h["rooms"]["R12"]["monsters"].append(
        {"id": "M19", "type": "gargoyle", "pos": [3, 10]}
    )
    good_quest_4h["rooms"]["R12"]["monsters"].append(
        {"id": "M20", "type": "gargoyle", "pos": [3, 11]}
    )
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("monster budget" in e and "outside" in e for e in errors)


def test_hard_difficulty_shifts_budget_target_up(good_quest_4h, good_quest_4h_params, catalogs):
    # Drop one goblin (cost 4): 126 -> 122. Still inside standard's
    # 108-132 range, but below hard's 124.2-151.8 floor -- proves the
    # +15% multiplier actually moves the target, not just widens it.
    good_quest_4h["rooms"]["R4"]["monsters"] = [
        m for m in good_quest_4h["rooms"]["R4"]["monsters"] if m["id"] != "M16"
    ]
    standard_errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert not any("monster budget" in e for e in standard_errors)

    hard_params = {**good_quest_4h_params, "difficulty": "hard"}
    hard_errors = check_balance(good_quest_4h, hard_params, catalogs)
    assert any("monster budget is 122" in e for e in hard_errors)


def test_room_monster_count_cap_exceeded(good_quest_4h, good_quest_4h_params, catalogs):
    # R2 already has 4 monsters, the 4-hero cap. A 5th trips the per-room count cap.
    good_quest_4h["rooms"]["R2"]["monsters"].append({"id": "M19", "type": "goblin", "pos": [8, 2]})
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("exceeding the 4-hero per-room cap" in e for e in errors)


def test_physical_per_type_room_cap_exceeded(good_quest_4h, good_quest_4h_params, catalogs):
    # R12 has 1 gargoyle already (the owned-mini cap); a 2nd in the same
    # room exceeds the physical cap even though the 4-hero room-count cap
    # (4) isn't hit.
    good_quest_4h["rooms"]["R12"]["monsters"].append({"id": "M19", "type": "gargoyle", "pos": [3, 10]})
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("exceeding the owned-mini cap of 1" in e for e in errors)


def test_objective_room_adjacent_to_stairway_rejected(good_quest_4h, good_quest_4h_params, catalogs):
    # check_balance only trusts door "squares" for area lookups (adjacency
    # itself is geometry.py's job), so a single fabricated door straight
    # from the stairway room to the objective room isolates the
    # depth/adjacency check without needing a real board wall edge.
    good_quest_4h["doors"] = [{"id": "D_DIRECT", "squares": [[1, 1], [1, 10]], "state": "open"}]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("adjacent to the stairway room R1" in e for e in errors)


def test_objective_room_too_shallow_rejected(good_quest_4h, good_quest_4h_params, catalogs):
    # Move the objective to R4, which is only 4 doors from R1 (below full's MIN_DEPTH of 5).
    good_quest_4h["objective"]["target"]["monsterId"] = "M13"
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("door(s) from the stairway" in e for e in errors)


def test_room_trap_cap_exceeded(good_quest_4h, good_quest_4h_params, catalogs):
    good_quest_4h["rooms"]["R3"]["traps"].append({"type": "falling_block", "pos": [11, 5]})
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("exceeding the cap of 1 per room" in e for e in errors)


def test_corridor_trap_cap_exceeded(good_quest_4h, good_quest_4h_params, catalogs):
    good_quest_4h["corridorTraps"] += [
        {"type": "pit", "pos": [1, 0]},
        {"type": "pit", "pos": [2, 0]},
        {"type": "pit", "pos": [3, 0]},
    ]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("exceeding the cap of 3" in e for e in errors)


def test_wandering_monster_too_costly_for_low_hero_count_rejected(good_quest_1h, good_quest_1h_params, catalogs):
    good_quest_1h["wanderingMonster"] = "gargoyle"  # cost 13 > 8
    errors = check_balance(good_quest_1h, good_quest_1h_params, catalogs)
    assert any("exceeding the 8-cost cap" in e for e in errors)


def test_wandering_monster_at_cost_boundary_accepted(good_quest_1h, good_quest_1h_params, catalogs):
    # good_quest_1h already uses fimir (cost 8), exactly at the cap.
    errors = check_balance(good_quest_1h, good_quest_1h_params, catalogs)
    assert not any("wandering" in e.lower() for e in errors)


def test_wandering_monster_unrestricted_for_high_hero_count(good_quest_4h, good_quest_4h_params, catalogs):
    good_quest_4h["wanderingMonster"] = "gargoyle"  # cost 13, fine at 4 heroes
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert not any("wandering" in e.lower() for e in errors)


def test_unknown_wandering_monster_rejected(good_quest_4h, good_quest_4h_params, catalogs):
    good_quest_4h["wanderingMonster"] = "beholder"
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("not a known monster type" in e for e in errors)


def test_furniture_owned_count_exceeded(good_quest_4h, good_quest_4h_params, catalogs):
    # tomb is owned x1 and already used once in R12; a 2nd anywhere trips the cap.
    good_quest_4h["rooms"]["R3"]["furniture"].append({"type": "tomb", "pos": [11, 4]})
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("exceeding the owned count of 1" in e for e in errors)


def test_door_total_count_cap_exceeded(good_quest_4h, good_quest_4h_params, catalogs):
    extra = [
        {"id": f"D_EXTRA{i}", "squares": [[4, 1], [5, 1]], "state": "open"}
        for i in range(16)
    ]
    good_quest_4h["doors"] += extra
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("exceeding the owned count of 21" in e for e in errors)


def test_every_door_may_be_closed(good_quest_4h, good_quest_4h_params, catalogs):
    # All doors start closed in play anyway, and the closed piece is
    # recycled as soon as Zargon swaps in an open one -- so the count of
    # closed doors caps nothing physical.
    for d in good_quest_4h["doors"]:
        d["state"] = "closed"
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert not any("door" in e for e in errors)




def test_blocked_squares_beyond_the_owned_tiles_rejected(good_quest_4h, good_quest_4h_params, catalogs):
    # 8 single + 2 double tiles cover 12 squares; a 13th has no tile.
    good_quest_4h["blockedSquares"] = [[x, 0] for x in range(13)]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("more than the 12 squares the owned tiles cover" in e for e in errors)


def test_twelve_blocked_squares_in_one_run_accepted(good_quest_4h, good_quest_4h_params, catalogs):
    # A single run of 12 contains plenty of adjacent pairs for the two
    # double tiles, so it lays out fine.
    good_quest_4h["blockedSquares"] = [[x, 0] for x in range(12)]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert not any("blocked squares" in e for e in errors)


def test_scattered_blocked_squares_past_the_single_tiles_rejected(good_quest_4h, good_quest_4h_params, catalogs):
    # 9 squares, none adjacent to another: the 9th would need a double
    # tile, and a double tile covers two ADJACENT squares or nothing.
    good_quest_4h["blockedSquares"] = [[x, 0] for x in range(0, 18, 2)]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("can't be laid out with" in e for e in errors)


def test_eleven_blocked_squares_with_only_one_pair_rejected(good_quest_4h, good_quest_4h_params, catalogs):
    # 11 squares needs both double tiles, so it needs two DISJOINT
    # adjacent pairs -- one pair plus 9 loose squares doesn't fit.
    good_quest_4h["blockedSquares"] = [[0, 0], [1, 0]] + [[x, 2] for x in range(0, 18, 2)]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("can't be laid out with" in e for e in errors)


def test_a_carried_chaos_spell_costs_budget(good_quest_4h, good_quest_4h_params, catalogs):
    from validator.balance import CHAOS_SPELL_THREAT_COST, _monster_threat_cost

    boss = good_quest_4h["rooms"]["R12"]["monsters"][0]
    entry = catalogs.monsters[boss["type"]]
    before = _monster_threat_cost(boss, entry)
    boss["spells"] = ["sleep", "fear"]
    assert _monster_threat_cost(boss, entry) == before + 2 * CHAOS_SPELL_THREAT_COST


def test_only_a_named_monster_may_carry_spells(good_quest_4h, good_quest_4h_params, catalogs):
    # "You must give your Chaos spells to specific monsters called for in
    # the Quest notes" -- a nameless orc in the crowd isn't one of those.
    rank_and_file = good_quest_4h["rooms"]["R2"]["monsters"][0]
    rank_and_file.pop("name", None)
    rank_and_file["spells"] = ["fear"]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("has no name" in e for e in errors)


def test_one_physical_card_of_each_spell(good_quest_4h, good_quest_4h_params, catalogs):
    for room_id, monster_index in (("R12", 0), ("R2", 0)):
        monster = good_quest_4h["rooms"][room_id]["monsters"][monster_index]
        monster["name"] = "A Named Villain"
        monster["spells"] = ["fear"]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("one physical card of each" in e for e in errors)


def test_escape_needs_a_destination_on_the_map(good_quest_4h, good_quest_4h_params, catalogs):
    boss = good_quest_4h["rooms"]["R12"]["monsters"][0]
    boss["name"] = "Verag"
    boss["spells"] = ["escape"]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("escapeDestination" in e for e in errors)

    good_quest_4h["escapeDestination"] = [3, 10]
    assert not any("escapeDestination" in e for e in check_balance(good_quest_4h, good_quest_4h_params, catalogs))


def test_an_unknown_card_is_rejected(good_quest_4h, good_quest_4h_params, catalogs):
    boss = good_quest_4h["rooms"]["R12"]["monsters"][0]
    boss["name"] = "Verag"
    boss["spells"] = ["meteor_swarm"]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("unknown Chaos spell" in e for e in errors)


def test_only_a_couple_of_monsters_may_carry_spells(good_quest_4h, good_quest_4h_params, catalogs):
    # The quest book arms the villain and maybe a lieutenant. A dungeon
    # of casters is a different game.
    armed = 0
    for room in good_quest_4h["rooms"].values():
        for monster in room["monsters"]:
            if armed >= 3:
                break
            monster["name"] = f"Villain {armed}"
            monster["spells"] = [["fear"], ["sleep"], ["rust"]][armed]
            armed += 1
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("more than the 2 the quest book ever arms" in e for e in errors)


@pytest.mark.parametrize("monster_type", ["orc", "goblin", "skeleton", "zombie", "mummy", "fimir"])
def test_a_non_casting_type_may_not_carry_chaos_spells(
    monster_type, good_quest_4h, good_quest_4h_params, catalogs
):
    # An orc with a name is still an orc, and the shambling undead
    # never cast at all.
    monster = good_quest_4h["rooms"]["R2"]["monsters"][0]
    monster["type"] = monster_type
    monster["name"] = "Grukk the Loud"
    monster["spells"] = ["fear"]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("can't carry Chaos spells" in e for e in errors)


@pytest.mark.parametrize("monster_type", ["chaos_warrior", "chaos_warlock", "gargoyle"])
def test_a_casting_type_may_carry_chaos_spells(
    monster_type, good_quest_4h, good_quest_4h_params, catalogs
):
    # The three figures the owner actually arms: 4 chaos warriors,
    # 1 chaos warlock, 1 gargoyle.
    monster = good_quest_4h["rooms"]["R2"]["monsters"][0]
    monster["type"] = monster_type
    monster["name"] = "Grukk the Loud"
    monster["spells"] = ["fear"]
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert not any("can't carry Chaos spells" in e for e in errors)


def test_caster_types_are_the_three_owned_figures(catalogs):
    assert caster_types(catalogs) == ["chaos_warlock", "chaos_warrior", "gargoyle"]
