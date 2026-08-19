from validator.balance import check_balance


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


def test_locked_door_cap_exceeded(good_quest_4h, good_quest_4h_params, catalogs):
    for d in good_quest_4h["doors"]:
        d["state"] = "locked"
    errors = check_balance(good_quest_4h, good_quest_4h_params, catalogs)
    assert any("locked doors, exceeding the cap of 5" in e for e in errors)
