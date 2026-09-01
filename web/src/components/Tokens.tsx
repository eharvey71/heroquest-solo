/**
 * Token layer: heroes and monsters, drawn only on revealed squares --
 * a monster the party hasn't uncovered yet must stay hidden, same as
 * the terrain it stands on. Purely presentational -- pointer handling
 * lives in BoardView (see its coordFromEvent), which needs one
 * coordinate-math-based handler for reliable drag-tracing anyway, so
 * per-token click handlers here would just be a second, redundant
 * interaction path.
 *
 * A token that has moved WALKS to its new square: one square at a
 * time along the route the figure actually took (game.lastMoves,
 * written by every endpoint that moves a figure), so it turns the
 * corridor's corners the way the mini does on the table. The old CSS
 * transition could only tween a straight line, and a straight line
 * between two corridor squares cuts through walls. Where no route is
 * known -- an undo further back than one action, Escape's teleport, a
 * game loaded mid-play -- the token slides straight, or simply appears.
 */

import { useEffect, useRef, useState } from "react";
import { type Coord, squareKey } from "../lib/board";
import type { HeroToken, MonsterToken } from "../lib/gameState";

interface TokensProps {
  cellSize: number;
  heroes: HeroToken[];
  monsters: MonsterToken[];
  revealed: ReadonlySet<string>;
  /** game.lastMoves: the squares each figure walked in the action just
   * written, start square first. Only walked when its two ends match
   * where the token is drawn and where it now stands. */
  paths?: Record<string, Coord[]>;
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

/** Time to cross one square. A 12-square dash takes under two seconds,
 * long enough to follow, short enough not to hold up the next click. */
const STEP_MS = 140;
/** The straight slide used when no route is known. */
const SLIDE_MS = 350;

const NO_PATHS: Record<string, Coord[]> = {};

interface Walk {
  path: Coord[];
  startedAt: number;
  msPerStep: number;
}

function samePos(a: Coord, b: Coord): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

function onSquare(c: Coord): boolean {
  return Number.isInteger(c[0]) && Number.isInteger(c[1]);
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Where each figure is DRAWN, which lags where it IS while a walk is
 * in progress. Keyed by figure id; positions are fractional mid-step.
 *
 * Matching rule for a route: it must start on the square the token is
 * drawn on and end on the figure's new square. A stale entry (a
 * document write that moved nothing leaves the previous one in place)
 * therefore can't send a token the wrong way -- it just fails to match
 * and the token slides straight. The previous document's routes are
 * kept for one more comparison so that an undo of the last move walks
 * the figure BACK along the same squares.
 */
function useWalkedPositions(
  figures: readonly { id: string; pos: Coord }[],
  paths: Record<string, Coord[]>
): Record<string, Coord> {
  const [drawn, setDrawn] = useState<Record<string, Coord>>({});
  const drawnRef = useRef<Record<string, Coord>>({});
  const walksRef = useRef<Record<string, Walk>>({});
  const rafRef = useRef<number | null>(null);
  const lastPathsRef = useRef<Record<string, Coord[]>>(paths);
  const prevPathsRef = useRef<Record<string, Coord[]>>({});

  useEffect(() => {
    const tick = (now: number) => {
      rafRef.current = null;
      const walks = walksRef.current;
      const ids = Object.keys(walks);
      if (ids.length === 0) return;
      const next = { ...drawnRef.current };
      for (const id of ids) {
        const w = walks[id];
        const steps = w.path.length - 1;
        // The frame's timestamp can be a hair EARLIER than the
        // performance.now() the walk was stamped with (it is the
        // frame's start, not the callback's), so clamp -- a negative t
        // indexed the path at -1 and crashed the first step.
        const t = Math.max(0, (now - w.startedAt) / w.msPerStep);
        if (t >= steps) {
          next[id] = w.path[steps];
          delete walks[id];
          continue;
        }
        const i = Math.min(Math.floor(t), steps - 1);
        const f = t - i;
        const a = w.path[i];
        const b = w.path[i + 1];
        next[id] = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
      }
      drawnRef.current = next;
      setDrawn(next);
      if (Object.keys(walks).length > 0) rafRef.current = requestAnimationFrame(tick);
    };

    // A new document: the previous one's routes are what an undo would
    // have to retrace.
    if (paths !== lastPathsRef.current) {
      prevPathsRef.current = lastPathsRef.current;
      lastPathsRef.current = paths;
    }

    const reduceMotion = prefersReducedMotion();
    const now = performance.now();
    const walks = walksRef.current;
    const next = { ...drawnRef.current };
    const seen = new Set<string>();
    let changed = false;

    for (const fig of figures) {
      seen.add(fig.id);
      const cur = next[fig.id];
      if (!cur || reduceMotion) {
        // First appearance (a game loaded, a monster revealed or
        // spawned) -- it is simply there. No route to walk.
        if (!cur || !samePos(cur, fig.pos)) {
          next[fig.id] = fig.pos;
          changed = true;
        }
        delete walks[fig.id];
        continue;
      }
      const walk = walks[fig.id];
      if (walk && samePos(walk.path[walk.path.length - 1], fig.pos)) continue; // already on its way there
      if (samePos(cur, fig.pos)) {
        delete walks[fig.id];
        continue;
      }
      let route: Coord[] | null = null;
      if (onSquare(cur)) {
        const forward = paths[fig.id];
        const back = prevPathsRef.current[fig.id];
        if (forward && forward.length > 1 && samePos(forward[0], cur) && samePos(forward[forward.length - 1], fig.pos)) {
          route = forward;
        } else if (back && back.length > 1 && samePos(back[back.length - 1], cur) && samePos(back[0], fig.pos)) {
          route = [...back].reverse();
        }
      }
      walks[fig.id] = route
        ? { path: route, startedAt: now, msPerStep: STEP_MS }
        : { path: [cur, fig.pos], startedAt: now, msPerStep: SLIDE_MS };
    }
    for (const id of Object.keys(next)) {
      if (!seen.has(id)) {
        // Fallen, or slain: the figure leaves the board.
        delete next[id];
        delete walks[id];
        changed = true;
      }
    }

    if (changed) {
      drawnRef.current = next;
      setDrawn(next);
    }
    if (Object.keys(walks).length > 0 && rafRef.current === null) {
      rafRef.current = requestAnimationFrame(tick);
    }
  }, [figures, paths]);

  useEffect(
    () => () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    },
    []
  );

  return drawn;
}

export function Tokens({
  cellSize,
  heroes,
  monsters,
  revealed,
  paths = NO_PATHS,
  activeHeroId,
  activeMonsterId,
  attackingMonsterIds,
}: TokensProps) {
  const radius = cellSize * 0.36;

  // Hidden monsters are left out of the walk entirely: a figure that
  // steps into view for the first time appears on its square, and one
  // that is drawn only walks through squares the party can see (Zargon
  // paths through revealed territory only).
  const figures = useRef<{ id: string; pos: Coord }[]>([]);
  const visible = [
    ...monsters.filter((m) => m.alive && revealed.has(squareKey(m.pos[0], m.pos[1]))),
    ...heroes,
  ].map((f) => ({ id: f.id, pos: f.pos }));
  const unchanged =
    visible.length === figures.current.length &&
    visible.every((f, i) => f.id === figures.current[i].id && samePos(f.pos, figures.current[i].pos));
  if (!unchanged) figures.current = visible;
  const drawn = useWalkedPositions(figures.current, paths);

  const centre = (id: string, pos: Coord): [number, number] => {
    const at = drawn[id] ?? pos;
    return [at[0] * cellSize + cellSize / 2, at[1] * cellSize + cellSize / 2];
  };

  return (
    <g>
      {monsters.map((m) => {
        if (!m.alive) return null;
        if (!revealed.has(squareKey(m.pos[0], m.pos[1]))) return null;
        const [cx, cy] = centre(m.id, m.pos);
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
        const [cx, cy] = centre(h.id, h.pos);
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
