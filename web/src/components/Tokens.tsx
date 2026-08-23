/**
 * Token layer: heroes and monsters, drawn only on revealed squares --
 * a monster the party hasn't uncovered yet must stay hidden, same as
 * the terrain it stands on. Purely presentational -- pointer handling
 * lives in BoardView (see its coordFromEvent), which needs one
 * coordinate-math-based handler for reliable drag-tracing anyway, so
 * per-token click handlers here would just be a second, redundant
 * interaction path.
 */

import { squareKey } from "../lib/board";
import type { HeroToken, MonsterToken } from "../lib/gameState";

interface TokensProps {
  cellSize: number;
  heroes: HeroToken[];
  monsters: MonsterToken[];
  revealed: ReadonlySet<string>;
  /** The Active Hero rail selection, not the mid-trace path-input
   * selection -- the two are usually the same hero (tapping a token
   * sets both), but a dropdown change without touching the board only
   * moves this one, and the board should still reflect it. */
  activeHeroId?: string;
  /** The monster picked in the Attack or Cast Spell dropdown. */
  activeMonsterId?: string;
  /** Monsters with an unanswered defence prompt -- whoever just
   * attacked and is still waiting on a shield report. Drawn as a ring
   * so it composes with (rather than fights) the targeting highlight
   * above, on the rare turn a monster is both. */
  attackingMonsterIds?: ReadonlySet<string>;
}

const HERO_FILL = "#4a7fd6";
const HERO_ACTIVE_FILL = "#7fb0ff";
const MONSTER_FILL = "#c23b3b";
const MONSTER_ACTIVE_FILL = "#e06a6a";
// Same amber the "waiting on you" rail alerts use, so the board and the
// defence prompt read as the same thing.
const ATTACKING_RING = "#e8b04a";

export function Tokens({
  cellSize,
  heroes,
  monsters,
  revealed,
  activeHeroId,
  activeMonsterId,
  attackingMonsterIds,
}: TokensProps) {
  const radius = cellSize * 0.36;

  return (
    <g>
      {monsters.map((m) => {
        if (!m.alive) return null;
        if (!revealed.has(squareKey(m.pos[0], m.pos[1]))) return null;
        const cx = m.pos[0] * cellSize + cellSize / 2;
        const cy = m.pos[1] * cellSize + cellSize / 2;
        const isActive = m.id === activeMonsterId;
        const isAttacking = attackingMonsterIds?.has(m.id) ?? false;
        return (
          <g key={m.id} className="token-figure" style={{ transform: `translate(${cx}px, ${cy}px)` }}>
            {isAttacking && <circle r={radius + 4} fill="none" stroke={ATTACKING_RING} strokeWidth={2.5} />}
            <circle
              r={radius}
              fill={isActive ? MONSTER_ACTIVE_FILL : MONSTER_FILL}
              stroke={isActive ? "#fff" : "#1a1414"}
              strokeWidth={isActive ? 2.5 : 1.5}
            />
            <text textAnchor="middle" dominantBaseline="central" fontSize={cellSize * 0.32} fill="#fff" pointerEvents="none">
              {m.type[0]?.toUpperCase()}
            </text>
          </g>
        );
      })}
      {heroes.map((h) => {
        // Heroes are player-controlled and always visible on the digital
        // board once placed -- they're not subject to fog the way
        // monsters/terrain are (the party always knows where its own
        // members are standing).
        const cx = h.pos[0] * cellSize + cellSize / 2;
        const cy = h.pos[1] * cellSize + cellSize / 2;
        const isSelected = h.id === activeHeroId;
        return (
          <g key={h.id} className="token-figure" pointerEvents="none" style={{ transform: `translate(${cx}px, ${cy}px)` }}>
            <circle
              r={radius}
              fill={isSelected ? HERO_ACTIVE_FILL : HERO_FILL}
              stroke={isSelected ? "#fff" : "#1a1414"}
              strokeWidth={isSelected ? 2.5 : 1.5}
            />
            <text textAnchor="middle" dominantBaseline="central" fontSize={cellSize * 0.32} fill="#fff" pointerEvents="none">
              {h.name[0]?.toUpperCase()}
            </text>
          </g>
        );
      })}
    </g>
  );
}
