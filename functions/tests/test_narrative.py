from validator.narrative import check_narrative


def test_good_quest_has_no_narrative_warnings(good_quest_4h):
    assert check_narrative(good_quest_4h) == []


def test_short_backstory_warns(good_quest_4h):
    good_quest_4h["backstory"] = "Too short."
    warnings = check_narrative(good_quest_4h)
    assert any("backstory is" in w for w in warnings)


def test_long_reveal_text_warns(good_quest_4h):
    good_quest_4h["rooms"]["R2"]["revealText"] = " ".join(["word"] * 41)
    warnings = check_narrative(good_quest_4h)
    assert any("R2 revealText is 41 words" in w for w in warnings)


def test_long_completion_text_warns(good_quest_4h):
    good_quest_4h["completionText"] = " ".join(["word"] * 101)
    warnings = check_narrative(good_quest_4h)
    assert any("completionText is 101 words" in w for w in warnings)


def test_narrative_warnings_do_not_fail_validation(good_quest_4h, good_quest_4h_params, catalogs):
    from validator.core import validate_quest

    good_quest_4h["backstory"] = "Too short."
    result = validate_quest(good_quest_4h, good_quest_4h_params, catalogs)
    assert result.ok  # warnings, not errors
    assert result.warnings
