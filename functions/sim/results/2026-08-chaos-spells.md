# What does a Chaos-spell boss cost?

**Answer: about 2 threat points per card carried**, which is what
`CHAOS_SPELL_THREAT_COST` now charges. The measured cost is lower than
that; 2 rounds it up rather than down.

Method as in ../README.md: same 200 seeds per cell, one thing changed.
The boss carries the three harshest cards in the deck -- Firestorm
(3 Body Points to everyone in its room), Cloud of Chaos (paralyses the
room) and Sleep.

```
                          games   win% turns  dead   BP lost   kills
4 heroes, no spells         200   95.5  28.8  0.89   10.0+-0.5  15.8
4 heroes, three spells      200   93.0  29.2  0.95   10.5+-0.5  15.8
2 heroes, no spells         200   91.5  28.1  0.28    5.6+-0.3  11.0
2 heroes, three spells      200   90.5  28.2  0.30    5.9+-0.3  10.9
```

+0.5 Body Points at four heroes, and 2.5 points off the win rate. The
budget sweep (see 2026-08-attack-then-move.md) prices 10% of budget at
~1.4 Body Points, so three cards cost roughly **3.5% of budget -- about
4 threat points, or 1.4 per card**.

## Why so cheap?

Because most cards are never spent:

```
60 games, 29 spells cast (0.48 per game, out of 3 held)
  firestorm        cast in  9 games (15%)
  cloud_of_chaos   cast in  6 games (10%)
  sleep            cast in 14 games (23%)
```

A boss has to survive to its own turn, see a hero, and -- for the
room-wide cards -- see two. Parties tend to open the door and kill it
first. So a card is worth much less than its effect suggests: the
effect is large, the chance of landing it is not.

Two caveats before leaning on that number. The simulated party never
retreats and never fears a room, so it hands the boss fewer chances than
a cautious human party would. And breaking a hold is a Mind Point roll,
where the sim's Wizard (6 dice) shrugs off Sleep far more reliably than
the Barbarian (2) -- a party that loses its Wizard early would feel
these cards much more sharply than the averages show.
