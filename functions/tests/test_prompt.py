import random

from generator.prompt import _campaign_section, build_system_prompt, pick_stairway_room, rooms_with_2x2_fit


def test_rooms_with_2x2_fit_only_includes_real_rooms(catalogs):
    fits = rooms_with_2x2_fit(catalogs)
    assert set(fits).issubset(catalogs.board.room_ids)
    assert len(fits) > 0


def test_pick_stairway_room_is_a_valid_fitting_room(catalogs):
    room = pick_stairway_room(catalogs, rng=random.Random(1))
    assert room in rooms_with_2x2_fit(catalogs)


def test_pick_stairway_room_varies_across_seeds(catalogs):
    # Not a guarantee for any two arbitrary seeds, but across a spread of
    # seeds the picks must not all collapse to the same room -- that's
    # exactly the bug being fixed (every quest starting in R1).
    picks = {pick_stairway_room(catalogs, rng=random.Random(seed)) for seed in range(20)}
    assert len(picks) > 1


def test_prompt_names_the_pinned_stairway_room(good_quest_4h_params, catalogs):
    prompt = build_system_prompt(good_quest_4h_params, catalogs, "R7")
    assert "R7" in prompt
    assert "pre-selected" in prompt


def test_campaign_section_empty_without_context():
    assert _campaign_section({"heroCount": 4}) == ""


def test_campaign_section_names_the_previous_quest_and_quotes_the_chronicle():
    params = {
        "heroCount": 4,
        "campaignContext": {"previousTitle": "The Tomb of the Ashen King", "chronicle": "They triumphed."},
    }
    section = _campaign_section(params)
    assert "The Tomb of the Ashen King" in section
    assert "They triumphed." in section
    assert "SEQUEL" in section


def test_prompt_omits_campaign_section_by_default(good_quest_4h_params, catalogs):
    prompt = build_system_prompt(good_quest_4h_params, catalogs, "R7")
    assert "CAMPAIGN CONTINUITY" not in prompt


def test_prompt_includes_campaign_section_when_present(good_quest_4h_params, catalogs):
    params = {
        **good_quest_4h_params,
        "campaignContext": {"previousTitle": "The Fire Mage", "chronicle": "Balur was slain."},
    }
    prompt = build_system_prompt(params, catalogs, "R7")
    assert "CAMPAIGN CONTINUITY" in prompt
    assert "Balur was slain." in prompt
