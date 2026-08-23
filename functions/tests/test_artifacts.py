from validator.artifacts import check_artifacts


def test_a_named_artifact_objective_is_valid(good_quest_4h, catalogs):
    good_quest_4h["objective"]["type"] = "find_artifact"
    good_quest_4h["objective"]["target"]["artifactId"] = "wand_of_magic"
    assert check_artifacts(good_quest_4h, catalogs) == []


def test_a_named_artifact_in_furniture_is_valid(good_quest_4h, catalogs):
    good_quest_4h["rooms"]["R2"]["furniture"] = good_quest_4h["rooms"]["R2"].get("furniture") or []
    good_quest_4h["rooms"]["R2"]["furniture"].append(
        {
            "type": "table",
            "pos": [1, 1],
            "orientation": "N",
            "contains": {"trap": "none", "treasure": "a few coins", "artifactId": "elixir_of_life"},
        }
    )
    assert check_artifacts(good_quest_4h, catalogs) == []


def test_an_unknown_objective_artifact_is_rejected(good_quest_4h, catalogs):
    good_quest_4h["objective"]["type"] = "find_artifact"
    good_quest_4h["objective"]["target"]["artifactId"] = "made_up_thing"
    errors = check_artifacts(good_quest_4h, catalogs)
    assert any("unknown artifact 'made_up_thing'" in e for e in errors)


def test_an_unknown_furniture_artifact_is_rejected(good_quest_4h, catalogs):
    good_quest_4h["rooms"]["R2"]["furniture"] = good_quest_4h["rooms"]["R2"].get("furniture") or []
    good_quest_4h["rooms"]["R2"]["furniture"].append(
        {
            "type": "table",
            "pos": [1, 1],
            "orientation": "N",
            "contains": {"trap": "none", "treasure": "text", "artifactId": "made_up_thing"},
        }
    )
    errors = check_artifacts(good_quest_4h, catalogs)
    assert any("unknown artifact 'made_up_thing'" in e for e in errors)


def test_the_same_artifact_cannot_be_placed_twice(good_quest_4h, catalogs):
    # There is one physical card of each -- an objective goal AND a
    # chest both naming the Wand of Magic is two copies of one card.
    good_quest_4h["objective"]["type"] = "find_artifact"
    good_quest_4h["objective"]["target"]["artifactId"] = "wand_of_magic"
    good_quest_4h["rooms"]["R2"]["furniture"] = good_quest_4h["rooms"]["R2"].get("furniture") or []
    good_quest_4h["rooms"]["R2"]["furniture"].append(
        {
            "type": "table",
            "pos": [1, 1],
            "orientation": "N",
            "contains": {"trap": "none", "treasure": "text", "artifactId": "wand_of_magic"},
        }
    )
    errors = check_artifacts(good_quest_4h, catalogs)
    assert any("wand_of_magic" in e and "placed 2 times" in e for e in errors)


def test_two_different_artifacts_may_coexist(good_quest_4h, catalogs):
    # Objective names one, a chest along the way holds a different one
    # -- both modes at once, no conflict.
    good_quest_4h["objective"]["type"] = "find_artifact"
    good_quest_4h["objective"]["target"]["artifactId"] = "wand_of_magic"
    good_quest_4h["rooms"]["R2"]["furniture"] = good_quest_4h["rooms"]["R2"].get("furniture") or []
    good_quest_4h["rooms"]["R2"]["furniture"].append(
        {
            "type": "table",
            "pos": [1, 1],
            "orientation": "N",
            "contains": {"trap": "none", "treasure": "text", "artifactId": "elixir_of_life"},
        }
    )
    assert check_artifacts(good_quest_4h, catalogs) == []


def test_a_quest_with_no_artifacts_at_all_is_fine(good_quest_4h, catalogs):
    assert check_artifacts(good_quest_4h, catalogs) == []


def test_the_catalog_has_all_ten_1989_artifact_cards(catalogs):
    assert set(catalogs.artifacts) == {
        "ring_of_return",
        "spell_ring",
        "talisman_of_lore",
        "spirit_blade",
        "borins_armor",
        "orcs_bane",
        "wizards_staff",
        "wizards_cloak",
        "elixir_of_life",
        "wand_of_magic",
    }
    for artifact_id, entry in catalogs.artifacts.items():
        assert entry["name"]
        assert entry["text"]
