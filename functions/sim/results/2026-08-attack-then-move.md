# Does attack-then-move need a budget change?

**Answer: no.** A withdrawing Zargon is within noise of the old
stay-put behaviour, and far inside the +-10% the validator already
tolerates. `BASELINE_BUDGET` stays at 120.

Run on the engine at the commit that introduced `WITHDRAW_POLICIES`.
Every cell plays the same 200 seeds, so rows differ by the rule and
nothing else. `BP lost` is mean party Body Points lost per quest, +-
one standard error.

## 1. Is the instrument sensitive at all?

Budget multiplier sweep under the old rules (`none`), 150 games/cell:

```
   policy heroes budget  games   win% timeout  turns  dead   BP lost  kills
     none      4   0.70    150   97.3     2.0   27.6  0.61    6.4+-0.4   11.8
     none      4   0.85    150   97.3     1.3   28.5  0.83    8.3+-0.5   14.1
     none      4   1.00    150   94.0     2.0   31.5  1.17   10.8+-0.5   16.6
     none      4   1.15    150   87.3     5.3   34.0  1.45   12.8+-0.6   18.4
     none      4   1.30    150   84.0     4.7   35.9  1.79   14.7+-0.6   20.3
     none      2   0.70    150   94.7     2.7   26.2  0.13    3.4+-0.3    8.2
     none      2   0.85    150   92.0     3.3   28.3  0.27    4.6+-0.4    9.8
     none      2   1.00    150   94.7     2.0   29.8  0.35    5.9+-0.4   11.5
     none      2   1.15    150   89.3     3.3   31.6  0.44    6.8+-0.4   12.9
     none      2   1.30    150   78.7     5.3   33.1  0.65    8.3+-0.4   14.0
```

Yes: **a 10% budget change moves BP lost by about 1.4 points** at four
heroes (6.4 -> 14.7 across a 0.7-1.3 sweep, near enough linear), and
win rate by about 3 points. That is the ruler everything else is
measured against.

## 2. What does the rule actually cost?

200 games/cell at budget 1.0:

```
   policy heroes budget  games   win% timeout  turns  dead   BP lost  kills
     none      4   1.00    200   93.5     2.5   30.8  1.15   10.5+-0.4   16.1
reposition      4   1.00    200   95.0     1.5   30.7  1.12   10.4+-0.4   16.1
 fall_back      4   1.00    200   95.5     1.0   28.8  0.89   10.0+-0.5   15.8
     none      2   1.00    200   94.5     2.5   29.2  0.32    5.7+-0.3   11.2
reposition      2   1.00    200   94.5     2.5   29.3  0.33    5.7+-0.3   11.2
 fall_back      2   1.00    200   91.5     1.5   28.1  0.28    5.6+-0.3   11.0
     none      1   1.00    200   93.5     2.5   15.7  0.04    2.1+-0.2    8.2
reposition      1   1.00    200   93.5     2.5   15.7  0.04    2.1+-0.2    8.2
 fall_back      1   1.00    200   93.0     2.0   15.5  0.05    2.1+-0.2    8.3
```

Between the hardest and softest policy the party loses 10.5 vs 10.0 BP
-- about a third of one standard error, and roughly what a **3% budget
change** would do. The prediction that hit-and-run would "raise
effective monster durability a long way" is not supported.

Why not: a monster that leaves melee also stops attacking. It spends
the following turn walking back into contact, so it trades damage
output for survivability at close to par. Kills per quest barely move
(16.1 -> 15.8), because most monsters die in the burst right after
their room is opened, before they have taken a turn at all.

## 3. How often does each policy fire?

Withdrawals as a share of monster turns, 30 games, 4 heroes:

```
none          0 / 507 monster turns    0.0%
reposition    6 / 500 monster turns    1.2%
fall_back   205 / 436 monster turns   47.0%
```

`reposition` is nearly a no-op: it only moves when the monster is
flanked AND a less exposed square adjacent to a hero exists, which
almost never comes up. `fall_back` is the policy with teeth, and it is
the one that measured free -- so it is the default.

## Caveats

The absolute win rates here (91-96%) are a property of this simulated
party, not of a real one: no equipment beyond starting weapons, no
potions, no spells, no treasure, and no tactical mistakes. Read the
differences between rows, never the rows themselves. See ../README.md.
