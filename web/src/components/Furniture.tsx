/**
 * Furniture layer: quest-declared pieces (table, throne, chest, etc.),
 * revealed-gated same as monsters -- CLAUDE.md's fog of war is about
 * room CONTENTS, and furniture is content, unlike the room shapes
 * BoardTerrain always shows (see its module doc).
 */

import { useMemo } from "react";
import { squareKey } from "../lib/board";
import { furnitureFootprint } from "../lib/furniture";
import type { QuestFurniture } from "../lib/useQuestMap";

interface FurnitureProps {
  cellSize: number;
  furniture: QuestFurniture[];
  revealed: ReadonlySet<string>;
}

const FILL = "#4a3d28";
const STROKE = "#c9a24a";

function label(type: string): string {
  return type.replace(/_/g, " ");
}

export function Furniture({ cellSize, furniture, revealed }: FurnitureProps) {
  const visible = useMemo(
    () => furniture.filter((f) => revealed.has(squareKey(f.pos[0], f.pos[1]))),
    [furniture, revealed]
  );

  return (
    <g pointerEvents="none">
      {visible.map((f, i) => {
        const size = furnitureFootprint(f);
        if (!size) return null;
        const [w, h] = size;
        const x = f.pos[0] * cellSize;
        const y = f.pos[1] * cellSize;
        const name = label(f.type);
        // Shrink the label until it fits the footprint's width (~0.6em
        // per character); tiny 1x1 pieces stay readable via the hover
        // tooltip either way.
        const fontSize = Math.min(cellSize * 0.28, (w * cellSize - 6) / (name.length * 0.62));
        return (
          <g key={`${f.roomId}-${f.type}-${i}`}>
            <title>{name}</title>
            <rect
              x={x + 1}
              y={y + 1}
              width={w * cellSize - 2}
              height={h * cellSize - 2}
              fill={FILL}
              stroke={STROKE}
              strokeWidth={1}
              rx={2}
            />
            <text
              x={x + (w * cellSize) / 2}
              y={y + (h * cellSize) / 2}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={fontSize}
              fill={STROKE}
            >
              {name}
            </text>
          </g>
        );
      })}
    </g>
  );
}
