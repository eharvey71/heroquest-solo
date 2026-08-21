"""Sweeps the simulator over rule sets and budgets, and prints a table.

    python -m sim.run --games 200
    python -m sim.run --games 500 --policies none free --budgets 0.7 1.0 1.3

Every cell plays the SAME seeds, so two rows differ only by the rule
being tested -- same dungeons, same dice, one thing changed. Read
sim/README.md before drawing conclusions from a number here.
"""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass

from engine.turn import WITHDRAW_POLICIES
from validator.catalogs import load_catalogs

from .play import play_quest
from .quest_factory import build_quest


@dataclass
class Cell:
    policy: str
    hero_count: int
    budget: float
    games: int
    wins: int
    timeouts: int
    turns: float
    heroes_lost: float
    damage: float
    damage_stderr: float
    kills: float

    @property
    def win_rate(self) -> float:
        return 100.0 * self.wins / self.games


def run_cell(catalogs, *, policy: str, hero_count: int, budget: float, games: int, size: str, seed_base: int) -> Cell:
    outcomes = []
    for i in range(games):
        seed = seed_base + i
        quest = build_quest(
            catalogs, hero_count=hero_count, size=size, budget_multiplier=budget, seed=seed
        )
        outcomes.append(play_quest(catalogs, quest, hero_count, withdraw_policy=policy, seed=seed))

    damage = [o.damage_taken for o in outcomes]
    return Cell(
        policy=policy,
        hero_count=hero_count,
        budget=budget,
        games=games,
        wins=sum(1 for o in outcomes if o.won),
        timeouts=sum(1 for o in outcomes if o.result == "timeout"),
        turns=statistics.fmean(o.turns for o in outcomes),
        heroes_lost=statistics.fmean(o.heroes_lost for o in outcomes),
        damage=statistics.fmean(damage),
        damage_stderr=(statistics.stdev(damage) / (len(damage) ** 0.5)) if len(damage) > 1 else 0.0,
        kills=statistics.fmean(o.monsters_killed for o in outcomes),
    )


def format_table(cells: list[Cell]) -> str:
    header = (
        f"{'policy':>9} {'heroes':>6} {'budget':>6} {'games':>6} "
        f"{'win%':>6} {'timeout':>7} {'turns':>6} {'dead':>5} {'BP lost':>9} {'kills':>6}"
    )
    lines = [header, "-" * len(header)]
    for c in cells:
        lines.append(
            f"{c.policy:>9} {c.hero_count:6} {c.budget:6.2f} {c.games:6} "
            f"{c.win_rate:6.1f} {100.0 * c.timeouts / c.games:7.1f} {c.turns:6.1f} "
            f"{c.heroes_lost:5.2f} {c.damage:6.1f}+-{c.damage_stderr:.1f} {c.kills:6.1f}"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=100, help="games per cell")
    parser.add_argument("--policies", nargs="+", default=list(WITHDRAW_POLICIES), choices=WITHDRAW_POLICIES)
    parser.add_argument("--hero-counts", nargs="+", type=int, default=[4, 3, 2, 1])
    parser.add_argument("--budgets", nargs="+", type=float, default=[1.0])
    parser.add_argument("--size", default="full", choices=("short", "full"))
    parser.add_argument("--seed-base", type=int, default=1000)
    parser.add_argument("--out", help="also write the table here")
    args = parser.parse_args(argv)

    catalogs = load_catalogs()
    cells = [
        run_cell(
            catalogs, policy=policy, hero_count=hero_count, budget=budget,
            games=args.games, size=args.size, seed_base=args.seed_base,
        )
        for policy in args.policies
        for budget in args.budgets
        for hero_count in args.hero_counts
    ]

    table = format_table(cells)
    print(table)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(table + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
