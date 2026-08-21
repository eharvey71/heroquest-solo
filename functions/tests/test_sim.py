"""The simulator's own guardrails.

Deliberately tiny: this suite proves the sim runs, terminates, and is
reproducible. It does NOT assert win rates -- those are measurements,
not invariants, and pinning them here would turn every balance tweak
into a test failure.
"""

from engine.turn import WITHDRAW_POLICIES
from sim.play import play_quest
from sim.quest_factory import build_quest
from sim.run import run_cell
from validator.balance import BASELINE_BUDGET, HERO_BUDGET_RATIO
from validator.reachability import check_reachability


def test_quest_factory_hits_the_budget_for_the_party(catalogs):
    for hero_count in (1, 2, 3, 4):
        quest = build_quest(catalogs, hero_count=hero_count, seed=7)
        target = BASELINE_BUDGET * HERO_BUDGET_RATIO[hero_count]
        assert 0.85 * target <= quest["threatSpent"] <= 1.15 * target


def test_quest_factory_builds_a_reachable_dungeon(catalogs):
    for seed in range(5):
        quest = build_quest(catalogs, hero_count=4, seed=seed)
        assert check_reachability(quest, catalogs) == []


def test_budget_multiplier_scales_the_roster(catalogs):
    light = build_quest(catalogs, hero_count=4, budget_multiplier=0.7, seed=3)
    heavy = build_quest(catalogs, hero_count=4, budget_multiplier=1.3, seed=3)
    assert light["threatSpent"] < heavy["threatSpent"]


def test_a_game_finishes_under_every_policy(catalogs):
    for policy in WITHDRAW_POLICIES:
        quest = build_quest(catalogs, hero_count=4, seed=11)
        outcome = play_quest(catalogs, quest, 4, withdraw_policy=policy, seed=11, max_turns=25)
        assert outcome.result in ("won", "wiped", "timeout")
        assert outcome.turns <= 25


def test_the_same_seed_replays_the_same_game(catalogs):
    quest = build_quest(catalogs, hero_count=2, seed=5)
    first = play_quest(catalogs, quest, 2, withdraw_policy="reposition", seed=5, max_turns=20)
    second = play_quest(catalogs, quest, 2, withdraw_policy="reposition", seed=5, max_turns=20)
    assert (first.result, first.turns, first.damage_taken) == (second.result, second.turns, second.damage_taken)


def test_a_cell_reports_what_it_played(catalogs):
    cell = run_cell(
        catalogs, policy="reposition", hero_count=4, budget=1.0, games=2, size="short", seed_base=99
    )
    assert cell.games == 2
    assert 0 <= cell.wins <= 2
    assert cell.kills >= 0
