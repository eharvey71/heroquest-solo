/**
 * Furniture layer: quest-declared pieces (table, throne, chest, etc.),
 * revealed-gated same as monsters -- CLAUDE.md's fog of war is about
 * room CONTENTS, and furniture is content, unlike the room shapes
 * BoardTerrain always shows (see its module doc).
 */

import { useMemo } from "react";
import furnitureCatalog from "../data/furniture.json";
import { squareKey } from "../lib/board";
import type { QuestFurniture } from "../lib/useQuestMap";

interface FurnitureProps {
  cellSize: number;
  furniture: QuestFurniture[];
  revealed: ReadonlySet<string>;
}

const FILL = "#4a3d28";
const STROKE = "#c9a24a";

const CATALOG = furnitureCatalog as Record<string, { footprint: number[]; owned: number }>;

function abbreviate(type: string): string {
  const parts = type.split("_");
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return type.slice(0, 2).toUpperCase();
}

export function Furniture({ cellSize, furniture, revealed }: FurnitureProps) {
  const visible = useMemo(
    () => furniture.filter((f) => revealed.has(squareKey(f.pos[0], f.pos[1]))),
    [furniture, revealed]
  );

  return (
    <g pointerEvents="none">
      {visible.map((f, i) => {
        const entry = CATALOG[f.type];
        if (!entry) return null;
        let [w, h] = entry.footprint;
        if (f.orientation === "E" || f.orientation === "W") [w, h] = [h, w];
        const x = f.pos[0] * cellSize;
        const y = f.pos[1] * cellSize;
        return (
          <g key={`${f.roomId}-${f.type}-${i}`}>
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
              fontSize={cellSize * 0.24}
              fill={STROKE}
            >
              {abbreviate(f.type)}
            </text>
          </g>
        );
      })}
    </g>
  );
}
