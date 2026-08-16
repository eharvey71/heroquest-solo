"""Sanity check: the hand-built good fixtures pass validation outright.
If these fail, something is wrong with the fixtures OR the validator is
too strict — either way, fix before trusting any other test in this
suite, since the "bad" tests all mutate copies of these fixtures.
"""

from validator.core import validate_quest


def test_good_4h_full_passes(good_quest_4h, good_quest_4h_params, catalogs):
    result = validate_quest(good_quest_4h, good_quest_4h_params, catalogs)
    assert result.errors == []
    assert result.ok


def test_good_1h_short_passes(good_quest_1h, good_quest_1h_params, catalogs):
    result = validate_quest(good_quest_1h, good_quest_1h_params, catalogs)
    assert result.errors == []
    assert result.ok
