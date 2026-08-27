import { useCallback, useMemo, useRef } from "react";
import { board as staticBoard, type Coord, squareKey } from "../lib/board";
import { isOrthogonallyAdjacent } from "../lib/boardGeometry";
import { livingHeroes, revealedSquareKeys, type GameState } from "../lib/gameState";
import type { QuestDoor, QuestFurniture, QuestStairway } from "../lib/useQuestMap";
import { BoardTerrain } from "./BoardTerrain";
import { Furniture } from "./Furniture";
import { PathOverlay } from "./PathOverlay";
import { Tokens } from "./Tokens";
import type { usePathInput } from "../hooks/usePathInput";

interface BoardViewProps {
  gameState: GameState;
  cellSize?: number;
  onSelectHero?: (heroId: string) => void;
  onSelectMonster?: (monsterId: string) => void;
  doors?: QuestDoor[];
  stairway?: QuestStairway | null;
  furniture?: QuestFurniture[];
  blockedSquares?: Coord[];
  /** The Active Hero rail selection -- highlighted on the board even
   * when it was set from the dropdown rather than by tapping a token. */
  activeHeroId?: string;
  /** The monster picked in the Attack or Cast Spell dropdown. */
  activeMonsterId?: string;
  /** Monsters with an unanswered defence prompt (pendingDefenses) --
   * whoever just attacked and is still waiting on a shield report. */
  attackingMonsterIds?: ReadonlySet<string>;
  /** Path-tracing state, owned by GameView so that "Moving X -- Confirm"
   * can sit in the rail beside the board rather than below it, where it
   * was easy to miss entirely. */
  pathInput: ReturnType<typeof usePathInput>;
}

export function BoardView({
  gameState,
  cellSize = 28,
  onSelectHero,
  onSelectMonster,
  doors,
  stairway,
  furniture = [],
  blockedSquares = [],
  activeHeroId,
  activeMonsterId,
  attackingMonsterIds,
  pathInput,
}: BoardViewProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const lastCoordKeyRef = useRef<string | null>(null);

  // Gutter for the coordinate labels along the top and left edges --
  // every log line and placement instruction names squares as [x,y],
  // so the axes show exactly those numbers (0-indexed, matching
  // board.json). The viewBox starts at -gutter so all board content
  // keeps its 0-based pixel coordinates.
  const gutter = cellSize * 0.8;

  const revealed = useMemo(() => revealedSquareKeys(staticBoard, gameState.revealed), [gameState.revealed]);
  // A fallen hero's figure comes off the board: nothing to draw, nothing
  // to select, and the square is free again (see engine/heroes.py).
  const heroes = useMemo(() => livingHeroes(gameState.heroes), [gameState.heroes]);
  const { selectedHeroId, path, isDragging, selectHero, extendTo, startDragging, stopDragging } = pathInput;

  const coordFromEvent = useCallback(
    (e: React.PointerEvent<SVGSVGElement>): Coord | null => {
      const svg = svgRef.current;
      if (!svg) return null;
      const rect = svg.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return null;
      // The viewBox starts at -gutter (the label margin), so the
      // client-to-board mapping subtracts it back out; a click in the
      // gutter itself lands negative and is rejected below.
      const scaleX = (staticBoard.width * cellSize + gutter) / rect.width;
      const scaleY = (staticBoard.height * cellSize + gutter) / rect.height;
      const localX = (e.clientX - rect.left) * scaleX - gutter;
      const localY = (e.clientY - rect.top) * scaleY - gutter;
      const bx = Math.floor(localX / cellSize);
      const by = Math.floor(localY / cellSize);
      if (bx < 0 || by < 0 || bx >= staticBoard.width || by >= staticBoard.height) return null;
      return [bx, by];
    },
    [cellSize, gutter]
  );

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      const coord = coordFromEvent(e);
      if (!coord) return;
      const key = squareKey(coord[0], coord[1]);

      // Heroes may move THROUGH fellow heroes (CLAUDE.md rules edition),
      // so a tap on a teammate can mean either "step onto that square"
      // or "switch to that hero". Adjacency decides: while a hero is
      // selected, a tap next to the path's end is always a step --
      // otherwise a teammate standing in a corridor was an unpassable
      // wall to a click-trace, since every tap on them re-selected them
      // and reset the path. Tapping a hero further off still switches,
      // and the rail's hero dropdown switches unconditionally.
      const last = path[path.length - 1];
      const steppingOn = selectedHeroId !== null && last !== undefined && isOrthogonallyAdjacent(last, coord);

      const heroHere = heroes.find((h) => squareKey(h.pos[0], h.pos[1]) === key);
      if (heroHere && !steppingOn) {
        selectHero(heroHere);
        onSelectHero?.(heroHere.id); // keep the action panel's active hero in sync
      } else if (heroHere) {
        extendTo(coord);
      } else if (!selectedHeroId || path.length <= 1) {
        // Not mid-trace: a tap on a visible monster picks it as the
        // attack target instead of starting a path (a path can never
        // pass through a monster square anyway).
        const monsterHere = gameState.monsters.find(
          (m) => m.alive && squareKey(m.pos[0], m.pos[1]) === key && revealed.has(key)
        );
        if (monsterHere) {
          onSelectMonster?.(monsterHere.id);
          return;
        }
        if (!selectedHeroId) return; // no active path and nothing clickable here
        extendTo(coord);
      } else {
        extendTo(coord);
      }
      lastCoordKeyRef.current = key;
      startDragging();
    },
    [
      coordFromEvent,
      heroes,
      gameState.monsters,
      revealed,
      selectHero,
      onSelectHero,
      onSelectMonster,
      selectedHeroId,
      path,
      extendTo,
      startDragging,
    ]
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      if (!isDragging) return;
      const coord = coordFromEvent(e);
      if (!coord) return;
      const key = squareKey(coord[0], coord[1]);
      if (key === lastCoordKeyRef.current) return;
      lastCoordKeyRef.current = key;
      // A fast drag can skip cells between pointermove events, which
      // would stall the trace (extendTo only accepts adjacent steps).
      // Bridge straight-line gaps by feeding the intermediate squares;
      // diagonal skips stay rejected -- the corner choice is the
      // player's to make.
      const last = path[path.length - 1];
      if (last) {
        const [lx, ly] = last;
        const [cx, cy] = coord;
        if (lx === cx && Math.abs(cy - ly) > 1) {
          const step = cy > ly ? 1 : -1;
          for (let y = ly + step; y !== cy; y += step) extendTo([lx, y]);
        } else if (ly === cy && Math.abs(cx - lx) > 1) {
          const step = cx > lx ? 1 : -1;
          for (let x = lx + step; x !== cx; x += step) extendTo([x, ly]);
        }
      }
      extendTo(coord);
    },
    [isDragging, coordFromEvent, extendTo, path]
  );

  const handlePointerUp = useCallback(() => {
    stopDragging();
  }, [stopDragging]);

  return (
    <div>
      <svg
        ref={svgRef}
        viewBox={`${-gutter} ${-gutter} ${staticBoard.width * cellSize + gutter} ${staticBoard.height * cellSize + gutter}`}
        width="100%"
        // Size comes from CSS (.board-pane svg), not from cellSize:
        // the viewBox means one number can't be both "how big it draws"
        // and "how big it appears". cellSize is now purely the internal
        // unit that stroke widths and labels are measured in.
        style={{ background: "#111", touchAction: "none", userSelect: "none" }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      >
        <g>
          {Array.from({ length: staticBoard.width }, (_, x) => (
            <text
              key={`ax-${x}`}
              x={(x + 0.5) * cellSize}
              y={-gutter * 0.32}
              textAnchor="middle"
              fontSize={cellSize * 0.42}
              fill="#8a8272"
            >
              {x}
            </text>
          ))}
          {Array.from({ length: staticBoard.height }, (_, y) => (
            <text
              key={`ay-${y}`}
              x={-gutter * 0.5}
              y={(y + 0.5) * cellSize + cellSize * 0.15}
              textAnchor="middle"
              fontSize={cellSize * 0.42}
              fill="#8a8272"
            >
              {y}
            </text>
          ))}
        </g>
        <BoardTerrain
          board={staticBoard}
          cellSize={cellSize}
          revealed={revealed}
          doors={doors}
          stairway={stairway}
          blockedSquares={blockedSquares}
        />
        <Furniture cellSize={cellSize} furniture={furniture} revealed={revealed} />
        {/* Traps the party knows about. Only trapsFound entries exist
            client-side (hidden ones stay in quest data server-side):
            armed ones get a warning marker, and a SPRUNG pit keeps a
            persistent open-pit ring -- its tile stays on the physical
            board, and it vanishing from the app read as a bug. Sprung
            spears are gone forever and falling blocks become collapsed
            (blocked) squares, so neither draws here. */}
        <g>
          {Object.entries(gameState.trapsFound ?? {})
            .filter(([, t]) => t.pos && revealed.has(squareKey(t.pos[0], t.pos[1])))
            .map(([id, t]) => {
              const sprung = (gameState.trapsTriggered ?? []).includes(id);
              const cx = (t.pos[0] + 0.5) * cellSize;
              const cy = (t.pos[1] + 0.5) * cellSize;
              if (sprung) {
                if (t.type !== "pit") return null;
                return (
                  <circle
                    key={`trap-${id}`}
                    cx={cx}
                    cy={cy}
                    r={cellSize * 0.34}
                    fill="#0d0b08"
                    stroke="#6b5b3e"
                    strokeWidth={2}
                  />
                );
              }
              return (
                <g key={`trap-${id}`}>
                  <path
                    d={`M ${cx} ${cy - cellSize * 0.32} L ${cx + cellSize * 0.3} ${cy + cellSize * 0.24} L ${cx - cellSize * 0.3} ${cy + cellSize * 0.24} Z`}
                    fill="#e8b04a"
                    stroke="#3a2f16"
                    strokeWidth={1}
                  />
                  <text
                    x={cx}
                    y={cy + cellSize * 0.18}
                    textAnchor="middle"
                    fontSize={cellSize * 0.42}
                    fontWeight={700}
                    fill="#3a2f16"
                  >
                    !
                  </text>
                </g>
              );
            })}
        </g>
        <PathOverlay cellSize={cellSize} path={path} />
        <Tokens
          cellSize={cellSize}
          heroes={heroes}
          monsters={gameState.monsters}
          revealed={revealed}
          activeHeroId={activeHeroId}
          activeMonsterId={activeMonsterId}
          attackingMonsterIds={attackingMonsterIds}
        />
      </svg>
      <div className="board-legend">
        {[
          ["#7fd67f", "open door"],
          ["#d69a4a", "closed door"],
          ["#e8c34a", "stairway"],
          ["#e8b04a", "known trap (still armed)"],
          ["#0d0b08", "open pit (sprung)"],
        ].map(([colour, label]) => (
          <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 12, height: 4, background: colour, display: "inline-block", border: "1px solid #555" }} />
            {label}
          </span>
        ))}
        <span>a secret door looks like plain wall until it is found</span>
      </div>

    </div>
  );
}
