# The simulator

A headless Monte Carlo playtester for the Zargon engine. It exists to
answer one question the calibrated 120-point budget cannot answer on its
own:

> when a rule changes how long monsters survive, how far does the budget
> have to move to keep quests at the same difficulty?

CLAUDE.md's balance system prices a monster at `attack + defend + body`.
That formula has no term for "and it withdraws after it swings", so any
rule that changes a monster's effective durability silently changes what
a 120-point quest feels like. This package measures the change instead
of guessing at it.

## Running it

```
python -m sim.run --games 200
python -m sim.run --games 500 --policies none free --budgets 0.7 1.0 1.3
python -m sim.run --games 300 --hero-counts 1 --size short
```

Roughly 0.4s per game on one core. Every cell in a sweep plays the same
seeds, so two rows differ by the rule under test and nothing else --
same dungeons, same dice.

## What is real and what is a model

**Real** — Zargon's entire side is the shipping engine: movement and
pathing, target selection, the turn-type roller, combat dice, traps,
doors, fog of war, wandering monsters, the guard rules. That is the
point: the thing being measured is the code that runs in the app.

**A model** — the heroes. `sim/play.py` scripts a party that explores
toward the objective, opens what it finds, fights what it meets, and
walks home. It does not carry equipment past its starting weapon, drink
potions, cast spells, search for treasure, retreat, or split up. Body
Points are physical in the real app (CLAUDE.md's boundary), so the sim
tracks them itself.

## Read the differences, not the numbers

The absolute win rate out of this sim is **not** the win rate of a real
party at a real table, and it should never be quoted as one. A party
with no equipment and no potions is strictly worse than a real one; a
party that never makes a tactical error is better. Those biases don't
cancel, and neither is measured.

What survives those biases is the *difference between two runs over the
same seeds*. So the calibration method is:

1. Establish sensitivity. Sweep the budget multiplier under the current
   rules and confirm the metric responds -- if a 30% budget change
   doesn't move the numbers, the instrument can't measure anything.
2. Measure the rule. Run the new rule at multiplier 1.0.
3. Convert. Find the budget multiplier under the OLD rules that produces
   the same difficulty as the new rule at 1.0. That ratio is what
   `BASELINE_BUDGET` should move by -- not the raw win rate.

Body Points lost is the primary metric, not win rate: a healthy 4-hero
party wins nearly everything, so the win rate saturates while damage
taken still moves. `sim/run.py` prints a standard error next to it so a
difference can be told from noise.

## Limits worth remembering

- Hero AI quality is a confound. A party that plays better makes every
  rule look weaker.
- Quests are synthetic (`sim/quest_factory.py`), not LLM-generated: real
  rooms, real doors, real threat budget, no story.
- `sim/heroes.py` uses the four 1989 hero cards. Equipment purchases
  between quests -- the thing that makes a real campaign party stronger
  over time -- are not modelled at all.
