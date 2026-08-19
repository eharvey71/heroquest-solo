"""End-to-end: validate_quest() wiring all checks together, not each
check module in isolation. Confirms geometry/reachability/balance
findings all surface together in one pass (see core.py's comment on why
checks don't short-circuit each other).
"""

from validator.core import validate_quest


def test_multiple_simultaneous_violations_all_reported(good_quest_4h, good_quest_4h_params, catalogs):
    good_quest_4h["rooms"]["R2"]["monsters"][0]["type"] = "beholder"  # geometry
    good_quest_4h["doors"] = [d for d in good_quest_4h["doors"] if d["id"] != "D6"]  # reachability
    good_quest_4h["wanderingMonster"] = "beholder"  # balance

    result = validate_quest(good_quest_4h, good_quest_4h_params, catalogs)
    assert not result.ok
    assert any("unknown type 'beholder'" in e for e in result.errors)
    assert any("R12 is unreachable" in e for e in result.errors)
    assert any("wanderingMonster 'beholder'" in e for e in result.errors)


def test_completely_empty_quest_reports_errors_not_crash(catalogs):
    result = validate_quest({}, {"heroCount": 4, "difficulty": "standard", "size": "full"}, catalogs)
    assert not result.ok
    assert any("stairway" in e for e in result.errors)


def test_stairway_room_mismatch_rejected_when_pinned(good_quest_4h, good_quest_4h_params, catalogs):
    # good_quest_4h's stairway is in R1 -- pin a different room and the
    # mismatch must be caught (generator.prompt.pick_stairway_room's
    # constraint is only useful if a model ignoring it gets rejected).
    params = {**good_quest_4h_params, "stairwayRoom": "R7"}
    result = validate_quest(good_quest_4h, params, catalogs)
    assert not result.ok
    assert any("stairway must be placed in room R7" in e for e in result.errors)


def test_stairway_room_match_when_pinned_is_fine(good_quest_4h, good_quest_4h_params, catalogs):
    params = {**good_quest_4h_params, "stairwayRoom": "R1"}
    result = validate_quest(good_quest_4h, params, catalogs)
    assert not any("pre-selected" in e for e in result.errors)
