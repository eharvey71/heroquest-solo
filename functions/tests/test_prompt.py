import random

from generator.prompt import build_system_prompt, pick_stairway_room, rooms_with_2x2_fit


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
