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
