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
  selectedHeroId?: string;
}

const HERO_FILL = "#4a7fd6";
const HERO_ACTIVE_FILL = "#7fb0ff";
const MONSTER_FILL = "#c23b3b";
const MONSTER_DEAD_FILL = "#5a3b3b";

export function Tokens({ cellSize, heroes, monsters, revealed, selectedHeroId }: TokensProps) {
  const radius = cellSize * 0.36;

  return (
    <g>
      {monsters.map((m) => {
        if (!m.alive) return null;
        if (!revealed.has(squareKey(m.pos[0], m.pos[1]))) return null;
        const cx = m.pos[0] * cellSize + cellSize / 2;
        const cy = m.pos[1] * cellSize + cellSize / 2;
        return (
          <g key={m.id}>
            <circle cx={cx} cy={cy} r={radius} fill={m.alive ? MONSTER_FILL : MONSTER_DEAD_FILL} stroke="#1a1414" strokeWidth={1.5} />
            <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central" fontSize={cellSize * 0.32} fill="#fff" pointerEvents="none">
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
        const isSelected = h.id === selectedHeroId;
        return (
          <g key={h.id} pointerEvents="none">
            <circle
              cx={cx}
              cy={cy}
              r={radius}
              fill={isSelected ? HERO_ACTIVE_FILL : HERO_FILL}
              stroke={isSelected ? "#fff" : "#1a1414"}
              strokeWidth={isSelected ? 2.5 : 1.5}
            />
            <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central" fontSize={cellSize * 0.32} fill="#fff" pointerEvents="none">
              {h.name[0]?.toUpperCase()}
            </text>
          </g>
        );
      })}
    </g>
  );
}
