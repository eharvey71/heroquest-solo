"""Shape rules for generated side quests (validator/side_quests.py):
the graph must be safe to play, the effects capped, the prose free of
the app's own ids. Built against the 4-hero fixture quest so hook
rooms, monsters and depths are real.
"""

import copy

import pytest

from validator.balance import _door_hop_depth
from validator.side_quests import check_side_quests


def _scene(**overrides):
    """A minimal valid optional scene: 3 passages, 2 terminals, one die
    test, one hero-only choice, and every passage keeping an untagged
    way forward."""
    sq = {
        "id": "SQ1",
        "kind": "optional",
        "title": "The Weeping Well",
        "setting": "cave",
        "hook": {"when": "prologue", "room": "", "npcName": "", "figureHint": "", "text": "A voice from the well."},
        "gateText": "",
        "start": "p1",
        "passages": {
            "p1": {
                "text": "The well breathes cold air. Something below is calling your names.",
                "choices": [
                    {"id": "c1", "label": "Climb down", "next": "p2"},
                    {"id": "c2", "label": "The Dwarf tests the rope", "requiresHero": "dwarf", "next": "p2"},
                ],
            },
            "p2": {
                "text": "The shaft narrows. A ledge, a drop, and a glint of metal beyond.",
                "choices": [
                    {
                        "id": "c1",
                        "label": "Leap the gap",
                        "test": {"kind": "combat_dice", "dice": 2, "needSkulls": 1, "success": "t_win", "failure": "p3"},
                    },
                    {"id": "c2", "label": "Turn back", "next": "t_lose"},
                ],
            },
            "p3": {
                "text": "You slip and catch yourself, bruised. The glint is still there.",
                "choices": [
                    {"id": "c1", "label": "Give up", "next": "t_lose"},
                    {"id": "c2", "label": "Edge along the wall", "next": "t_win"},
                ],
            },
        },
        "terminals": {
            "t_win": {
                "outcome": "success",
                "text": "The glint is a purse of old coin, dropped by someone who never climbed back.",
                "effects": [{"type": "announce_reward", "kind": "gold", "text": "You find 40 gold coins."}],
            },
            "t_lose": {
                "outcome": "failure",
                "text": "You climb out empty-handed, and colder than you went in.",
                "effects": [{"type": "announce_cost", "kind": "body", "text": "The cold costs one hero 1 Body Point."}],
            },
        },
        "retry": None,
    }
    sq.update(overrides)
    return sq


def _required(quest, **overrides):
    sq = _scene(id="SQ2", kind="required", title="The Black Candle", gateText="The Warlock's ward holds while the candle burns.")
    sq["terminals"]["t_win"]["effects"] = [{"type": "break_gate"}]
    sq["terminals"]["t_lose"]["effects"] = [{"type": "crack_gate"}]
    sq.update(overrides)
    return sq


WARD = {"kind": "ward", "targetMonsterId": "M17", "targetName": "Vorlag the Cruel"}


def test_a_minimal_optional_scene_passes(good_quest_4h, catalogs):
    assert check_side_quests([_scene()], good_quest_4h, catalogs, required_gate=None) == []


def test_required_scene_must_be_present_when_asked_for_and_absent_otherwise(good_quest_4h, catalogs):
    errors = check_side_quests([_scene()], good_quest_4h, catalogs, required_gate=WARD)
    assert any("exactly one side quest must be 'required'" in e for e in errors)
    errors = check_side_quests([_scene(), _required(good_quest_4h)], good_quest_4h, catalogs, required_gate=None)
    assert any("no side quest may be 'required'" in e for e in errors)
    assert check_side_quests([_scene(), _required(good_quest_4h)], good_quest_4h, catalogs, required_gate=WARD) == []


def test_prose_may_not_print_room_ids_or_coordinates(good_quest_4h, catalogs):
    sq = _scene()
    sq["passages"]["p1"]["text"] = "Go to R12 and stand on [14,9]."
    errors = check_side_quests([sq], good_quest_4h, catalogs, required_gate=None)
    assert any("passage p1" in e and "room id" in e for e in errors)


def test_a_loop_is_rejected_unless_it_is_the_declared_retry(good_quest_4h, catalogs):
    sq = _scene()
    sq["passages"]["p3"]["choices"][0] = {"id": "c1", "label": "Try the leap again", "next": "p2"}
    errors = check_side_quests([sq], good_quest_4h, catalogs, required_gate=None)
    assert any("loop" in e for e in errors)

    sq["retry"] = {"from": "p3", "to": "p2", "costText": "The second attempt costs 1 Body Point."}
    assert check_side_quests([sq], good_quest_4h, catalogs, required_gate=None) == []

    sq["retry"]["costText"] = ""
    errors = check_side_quests([sq], good_quest_4h, catalogs, required_gate=None)
    assert any("costText" in e for e in errors)


def test_every_passage_keeps_an_untagged_choice(good_quest_4h, catalogs):
    sq = _scene()
    sq["passages"]["p1"]["choices"][0]["requiresElement"] = "Fire"
    errors = check_side_quests([sq], good_quest_4h, catalogs, required_gate=None)
    assert any("no hero/element/flag requirement" in e for e in errors)


def test_choices_must_lead_to_real_nodes(good_quest_4h, catalogs):
    sq = _scene()
    sq["passages"]["p1"]["choices"][0]["next"] = "nowhere"
    errors = check_side_quests([sq], good_quest_4h, catalogs, required_gate=None)
    assert any("must name a node, got 'nowhere'" in e for e in errors)


def test_the_best_ending_is_capped(good_quest_4h, catalogs):
    sq = _scene()
    sq["terminals"]["t_win"]["effects"] = [
        {"type": "grant_artifact", "artifactId": "ring_of_return"},
        {"type": "weaken_monster", "monsterId": "M17", "stat": "body"},
    ]
    errors = check_side_quests([sq], good_quest_4h, catalogs, required_gate=None)
    assert any("worth 5 boon points, cap is 4" in e for e in errors)


def test_town_scenes_carry_the_armory_beat_and_nothing_else_does(good_quest_4h, catalogs):
    sq = _scene(setting="town")
    errors = check_side_quests([sq], good_quest_4h, catalogs, required_gate=None)
    assert any("armory_visit beat" in e for e in errors)
    for t in sq["terminals"].values():
        t["effects"].append({"type": "armory_visit"})
    assert check_side_quests([sq], good_quest_4h, catalogs, required_gate=None) == []

    cave = _scene()
    cave["terminals"]["t_win"]["effects"].append({"type": "armory_visit"})
    errors = check_side_quests([cave], good_quest_4h, catalogs, required_gate=None)
    assert any("only a town scene visits the Armory" in e for e in errors)


def test_required_success_must_break_the_gate(good_quest_4h, catalogs):
    sq = _required(good_quest_4h)
    sq["terminals"]["t_win"]["effects"] = []
    errors = check_side_quests([_scene(), sq], good_quest_4h, catalogs, required_gate=WARD)
    assert any("success must include break_gate" in e for e in errors)


def test_required_success_must_be_reachable_without_a_tagged_hero(good_quest_4h, catalogs):
    sq = _required(good_quest_4h)
    # Only the Dwarf's choice reaches p2 (and so the win); the untagged
    # choice now goes straight to the loss.
    sq["passages"]["p1"]["choices"][0]["next"] = "t_lose"
    errors = check_side_quests([_scene(), sq], good_quest_4h, catalogs, required_gate=WARD)
    assert any("reachable using only choices with no" in e for e in errors)


def test_required_hook_room_must_come_before_the_objective(good_quest_4h, catalogs):
    boss_room = "R12"
    sq = _required(good_quest_4h, hook={"when": "room", "room": boss_room, "npcName": "x", "figureHint": "", "text": "y"})
    errors = check_side_quests([_scene(), sq], good_quest_4h, catalogs, required_gate=WARD)
    assert any("must not be the objective's own room" in e for e in errors)

    goal_depth = _door_hop_depth(catalogs, good_quest_4h, "R1", boss_room)
    earlier = next(r for r in good_quest_4h["rooms"] if r != boss_room and _door_hop_depth(catalogs, good_quest_4h, "R1", r) < goal_depth)
    sq["hook"]["room"] = earlier
    assert check_side_quests([_scene(), sq], good_quest_4h, catalogs, required_gate=WARD) == []


def test_an_artifact_already_in_the_quest_cannot_be_granted_again(good_quest_4h, catalogs):
    quest = copy.deepcopy(good_quest_4h)
    quest["objective"]["target"]["artifactId"] = "ring_of_return"
    sq = _scene()
    sq["terminals"]["t_win"]["effects"] = [{"type": "grant_artifact", "artifactId": "ring_of_return"}]
    errors = check_side_quests([sq], quest, catalogs, required_gate=None)
    assert any("already placed elsewhere" in e for e in errors)


def test_the_boss_cannot_be_removed_by_a_scene(good_quest_4h, catalogs):
    sq = _scene()
    sq["terminals"]["t_win"]["effects"] = [{"type": "remove_monster", "monsterId": "M17"}]
    errors = check_side_quests([sq], good_quest_4h, catalogs, required_gate=None)
    assert any("boss cannot be removed" in e for e in errors)


def test_too_few_nodes_is_an_error(good_quest_4h, catalogs):
    sq = _scene()
    del sq["passages"]["p3"]
    sq["passages"]["p2"]["choices"][0]["test"]["failure"] = "t_lose"
    errors = check_side_quests([sq], good_quest_4h, catalogs, required_gate=None)
    assert any("passages+terminals, must be 5-10" in e for e in errors)


@pytest.mark.parametrize("count", [0, 4])
def test_side_quest_count_is_bounded(good_quest_4h, catalogs, count):
    scenes = [_scene(id=f"SQ{i}") for i in range(count)]
    errors = check_side_quests(scenes, good_quest_4h, catalogs, required_gate=None)
    assert errors
