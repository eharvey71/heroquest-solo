/**
 * Path-tracing state for hero movement input. Per CLAUDE.md: movement is
 * entered as a path drag/click-trace on the board (not a die-roll total)
 * so traps can trigger mid-move and Zargon always knows hero positions.
 * This hook only tracks the path itself -- BoardView owns translating
 * pointer events into board coordinates and drives selectHero/extendTo.
 */

import { useCallback, useState } from "react";
import { type Board, type Coord, squareKey } from "../lib/board";
import { isOrthogonallyAdjacent } from "../lib/boardGeometry";
import type { HeroToken, MonsterToken } from "../lib/gameState";

export interface UsePathInputArgs {
  board: Board;
  heroes: HeroToken[];
  monsters: MonsterToken[];
}

export function usePathInput({ board, heroes, monsters }: UsePathInputArgs) {
  const [selectedHeroId, setSelectedHeroId] = useState<string | null>(null);
  const [path, setPath] = useState<Coord[]>([]);
  const [isDragging, setIsDragging] = useState(false);

  const selectHero = useCallback((hero: HeroToken) => {
    setSelectedHeroId(hero.id);
    setPath([hero.pos]);
  }, []);

  const extendTo = useCallback(
    (coord: Coord) => {
      setPath((prev) => {
        if (prev.length === 0) return prev;
        const key = squareKey(coord[0], coord[1]);

        // Stepping back onto an earlier square in the path truncates to
        // there -- lets a player correct course without starting over.
        const existingIndex = prev.findIndex((c) => squareKey(c[0], c[1]) === key);
        if (existingIndex !== -1) return prev.slice(0, existingIndex + 1);

        const last = prev[prev.length - 1];
        if (!isOrthogonallyAdjacent(last, coord)) return prev;
        if (board.areaOf.get(key) === undefined) return prev; // off-board
        // Monsters block a path outright; heroes may pass through
        // fellow heroes (CLAUDE.md rules edition note), so only
        // monster occupancy is checked mid-path -- the end-square
        // occupancy (by anything) is checked separately in canConfirm.
        if (monsters.some((m) => m.alive && squareKey(m.pos[0], m.pos[1]) === key)) return prev;

        return [...prev, coord];
      });
    },
    [board, monsters]
  );

  const startDragging = useCallback(() => setIsDragging(true), []);
  const stopDragging = useCallback(() => setIsDragging(false), []);

  const clear = useCallback(() => {
    setSelectedHeroId(null);
    setPath([]);
    setIsDragging(false);
  }, []);

  let endSquareOccupied = false;
  if (path.length > 0) {
    const endKey = squareKey(path[path.length - 1][0], path[path.length - 1][1]);
    endSquareOccupied =
      heroes.some((h) => h.id !== selectedHeroId && squareKey(h.pos[0], h.pos[1]) === endKey) ||
      monsters.some((m) => m.alive && squareKey(m.pos[0], m.pos[1]) === endKey);
  }

  const canConfirm = path.length > 1 && !endSquareOccupied;

  return {
    selectedHeroId,
    path,
    isDragging,
    selectHero,
    extendTo,
    startDragging,
    stopDragging,
    clear,
    canConfirm,
  };
}
