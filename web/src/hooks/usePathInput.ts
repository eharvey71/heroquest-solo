/**
 * Path-tracing state for hero movement input. Per CLAUDE.md: movement is
 * entered as a path drag/click-trace on the board (not a die-roll total)
 * so traps can trigger mid-move and Zargon always knows hero positions.
 * This hook only tracks the path itself -- BoardView owns translating
 * pointer events into board coordinates and drives selectHero/extendTo.
 *
 * Only monsters on REVEALED squares block the trace here -- a hidden
 * monster silently rejecting a step would both feel broken and leak
 * fog-of-war information (the unexplainably untraceable square IS the
 * monster's position). The backend still stops the actual move against
 * every living monster, hidden or not; the client just doesn't
 * pre-announce it.
 *
 * Furniture blocks unconditionally: it's quest geometry the player can
 * already see on the physical board, not hidden information, and it's
 * solid for the same reason it is server-side.
 *
 * Walls and unopened doors block too. The engine always stopped the
 * hero at the threshold, but letting the line be DRAWN through a
 * closed door then silently truncating the move on confirm reads as a
 * bug -- and hides the fact that the door is the thing to act on. A
 * step between two areas is legal only across a door this game has
 * actually opened.
 */

import { useCallback, useState } from "react";
import { type Board, type Coord, squareKey } from "../lib/board";
import { crossingKey, isOrthogonallyAdjacent } from "../lib/boardGeometry";
import type { HeroToken, MonsterToken } from "../lib/gameState";

export interface UsePathInputArgs {
  board: Board;
  heroes: HeroToken[];
  monsters: MonsterToken[];
  revealed: ReadonlySet<string>;
  /** Squares covered by furniture -- impassable (see lib/furniture.ts). */
  furniture: ReadonlySet<string>;
  /** crossingKey -> door state, for every door in the quest. A crossing
   * with no entry is a plain wall. */
  doorEdges: ReadonlyMap<string, string>;
}

export function usePathInput({ board, heroes, monsters, revealed, furniture, doorEdges }: UsePathInputArgs) {
  const [selectedHeroId, setSelectedHeroId] = useState<string | null>(null);
  const [path, setPath] = useState<Coord[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [blockedHint, setBlockedHint] = useState<string | null>(null);

  const selectHero = useCallback((hero: HeroToken) => {
    setSelectedHeroId(hero.id);
    setPath([hero.pos]);
    setBlockedHint(null);
  }, []);

  const extendTo = useCallback(
    (coord: Coord) => {
      setPath((prev) => {
        if (prev.length === 0) return prev;
        const key = squareKey(coord[0], coord[1]);

        // Stepping back onto an earlier square in the path truncates to
        // there -- lets a player correct course without starting over.
        const existingIndex = prev.findIndex((c) => squareKey(c[0], c[1]) === key);
        if (existingIndex !== -1) {
          setBlockedHint(null);
          return prev.slice(0, existingIndex + 1);
        }

        const last = prev[prev.length - 1];
        if (!isOrthogonallyAdjacent(last, coord)) return prev;
        if (board.areaOf.get(key) === undefined) {
          setBlockedHint("that square is off the board");
          return prev;
        }
        // Crossing an area boundary needs an OPEN door on that exact
        // edge -- otherwise it's a wall, or a door still to be opened.
        const lastArea = board.areaOf.get(squareKey(last[0], last[1]));
        const curArea = board.areaOf.get(key);
        if (lastArea !== curArea) {
          const doorState = doorEdges.get(crossingKey(last, coord));
          if (doorState === undefined || doorState === "secret") {
            setBlockedHint("that's a wall -- there's no door there");
            return prev;
          }
          if (doorState !== "open") {
            setBlockedHint(
              doorState === "locked"
                ? "that door is locked -- it needs a key or spell"
                : "that door is closed -- stop at it and use the Open door button"
            );
            return prev;
          }
        }
        if (furniture.has(key)) {
          setBlockedHint("furniture blocks that square -- heroes can't move over it");
          return prev;
        }
        // Monsters block a path outright; heroes may pass through
        // fellow heroes (CLAUDE.md rules edition note), so only
        // monster occupancy is checked mid-path -- the end-square
        // occupancy (by anything) is checked separately in canConfirm.
        if (revealed.has(key) && monsters.some((m) => m.alive && squareKey(m.pos[0], m.pos[1]) === key)) {
          setBlockedHint("a monster blocks that square -- heroes can't move through monsters");
          return prev;
        }

        setBlockedHint(null);
        return [...prev, coord];
      });
    },
    [board, monsters, revealed, furniture, doorEdges]
  );

  const startDragging = useCallback(() => setIsDragging(true), []);
  const stopDragging = useCallback(() => setIsDragging(false), []);

  const clear = useCallback(() => {
    setSelectedHeroId(null);
    setPath([]);
    setIsDragging(false);
    setBlockedHint(null);
  }, []);

  let endSquareOccupied = false;
  if (path.length > 0) {
    const endKey = squareKey(path[path.length - 1][0], path[path.length - 1][1]);
    endSquareOccupied =
      heroes.some((h) => h.id !== selectedHeroId && squareKey(h.pos[0], h.pos[1]) === endKey) ||
      monsters.some((m) => m.alive && revealed.has(endKey) && squareKey(m.pos[0], m.pos[1]) === endKey);
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
    endSquareOccupied,
    blockedHint,
  };
}
