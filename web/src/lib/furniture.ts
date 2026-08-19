/**
 * Furniture geometry, shared by the renderer and the path tracer.
 *
 * Furniture is impassable (see functions/engine/hero_movement.py): a
 * table or tomb is a real obstruction on the physical board, so a
 * traced path can't cross it. The renderer needs the same footprint
 * math to draw the piece, hence one helper rather than two.
 */

import furnitureCatalog from "../data/furniture.json";
import { type Coord, squareKey } from "./board";
import type { QuestFurniture } from "./useQuestMap";

const CATALOG = furnitureCatalog as Record<string, { footprint: number[]; owned: number }>;

/** Footprint as rendered, with the E/W 90-degree swap applied. */
export function furnitureFootprint(f: QuestFurniture): [number, number] | null {
  const entry = CATALOG[f.type];
  if (!entry) return null;
  const [w, h] = entry.footprint;
  return f.orientation === "E" || f.orientation === "W" ? [h, w] : [w, h];
}

export function furnitureCells(f: QuestFurniture): Coord[] {
  const size = furnitureFootprint(f);
  if (!size) return [];
  const [w, h] = size;
  const cells: Coord[] = [];
  for (let dx = 0; dx < w; dx++) {
    for (let dy = 0; dy < h; dy++) cells.push([f.pos[0] + dx, f.pos[1] + dy]);
  }
  return cells;
}

/** Every square covered by any piece, as square keys. */
export function furnitureSquareKeys(furniture: QuestFurniture[]): Set<string> {
  const keys = new Set<string>();
  for (const f of furniture) {
    for (const [x, y] of furnitureCells(f)) keys.add(squareKey(x, y));
  }
  return keys;
}
