import { useCallback, useMemo, useRef } from "react";
import { board as staticBoard, type Coord, squareKey } from "../lib/board";
import { crossingKey } from "../lib/boardGeometry";
import { furnitureSquareKeys } from "../lib/furniture";
import { revealedSquareKeys, type GameState } from "../lib/gameState";
import type { QuestDoor, QuestFurniture, QuestStairway } from "../lib/useQuestMap";
import { BoardTerrain } from "./BoardTerrain";
import { Furniture } from "./Furniture";
import { PathOverlay } from "./PathOverlay";
import { Tokens } from "./Tokens";
import { usePathInput } from "../hooks/usePathInput";

interface BoardViewProps {
  gameState: GameState;
  cellSize?: number;
  onConfirmMove?: (heroId: string, path: Coord[]) => void;
  onSelectHero?: (heroId: string) => void;
  onSelectMonster?: (monsterId: string) => void;
  doors?: QuestDoor[];
  stairway?: QuestStairway | null;
  furniture?: QuestFurniture[];
}

export function BoardView({
  gameState,
  cellSize = 28,
  onConfirmMove,
  onSelectHero,
  onSelectMonster,
  doors,
  stairway,
  furniture = [],
}: BoardViewProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const lastCoordKeyRef = useRef<string | null>(null);

  const revealed = useMemo(() => revealedSquareKeys(staticBoard, gameState.revealed), [gameState.revealed]);
  const furnitureKeys = useMemo(() => furnitureSquareKeys(furniture), [furniture]);
  const collapsedKeys = useMemo(
    () => new Set((gameState.collapsedSquares ?? []).map((sq) => squareKey(sq[0], sq[1]))),
    [gameState.collapsedSquares]
  );
  // `doors` arrives with live game state already merged in (GameView's
  // resolvedDoors), so an entry here is the door's state right now.
  const doorEdges = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of doors ?? []) map.set(crossingKey(d.squares[0], d.squares[1]), d.state);
    return map;
  }, [doors]);

  const {
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
  } = usePathInput({
    board: staticBoard,
    heroes: gameState.heroes,
    monsters: gameState.monsters,
    revealed,
    furniture: furnitureKeys,
    collapsed: collapsedKeys,
    doorEdges,
  });

  const coordFromEvent = useCallback(
    (e: React.PointerEvent<SVGSVGElement>): Coord | null => {
      const svg = svgRef.current;
      if (!svg) return null;
      const rect = svg.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return null;
      const scaleX = (staticBoard.width * cellSize) / rect.width;
      const scaleY = (staticBoard.height * cellSize) / rect.height;
      const localX = (e.clientX - rect.left) * scaleX;
      const localY = (e.clientY - rect.top) * scaleY;
      const bx = Math.floor(localX / cellSize);
      const by = Math.floor(localY / cellSize);
      if (bx < 0 || by < 0 || bx >= staticBoard.width || by >= staticBoard.height) return null;
      return [bx, by];
    },
    [cellSize]
  );

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      const coord = coordFromEvent(e);
      if (!coord) return;
      const key = squareKey(coord[0], coord[1]);

      const heroHere = gameState.heroes.find((h) => squareKey(h.pos[0], h.pos[1]) === key);
      if (heroHere) {
        selectHero(heroHere);
        onSelectHero?.(heroHere.id); // keep the action panel's active hero in sync
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
      gameState.heroes,
      gameState.monsters,
      revealed,
      selectHero,
      onSelectHero,
      onSelectMonster,
      selectedHeroId,
      path.length,
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

  const selectedHero = gameState.heroes.find((h) => h.id === selectedHeroId);

  const handleConfirm = () => {
    if (!selectedHero || !canConfirm) return;
    onConfirmMove?.(selectedHero.id, path);
    clear();
  };

  return (
    <div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${staticBoard.width * cellSize} ${staticBoard.height * cellSize}`}
        width="100%"
        style={{
          maxWidth: staticBoard.width * cellSize,
          background: "#111",
          touchAction: "none",
          userSelect: "none",
        }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      >
        <BoardTerrain board={staticBoard} cellSize={cellSize} revealed={revealed} doors={doors} stairway={stairway} />
        <Furniture cellSize={cellSize} furniture={furniture} revealed={revealed} />
        <PathOverlay cellSize={cellSize} path={path} />
        <Tokens
          cellSize={cellSize}
          heroes={gameState.heroes}
          monsters={gameState.monsters}
          revealed={revealed}
          selectedHeroId={selectedHeroId ?? undefined}
        />
      </svg>
      <div
        style={{ marginTop: 6, display: "flex", gap: 14, flexWrap: "wrap", fontSize: "0.8rem", color: "#9a917c" }}
      >
        {[
          ["#7fd67f", "open door"],
          ["#d69a4a", "closed door"],
          ["#e8c34a", "stairway"],
        ].map(([colour, label]) => (
          <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 12, height: 4, background: colour, display: "inline-block" }} />
            {label}
          </span>
        ))}
        <span>a secret door looks like plain wall until it is found</span>
      </div>

      {selectedHero && (
        <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span>
            Moving {selectedHero.name}: {Math.max(path.length - 1, 0)} step(s)
          </span>
          <button onClick={handleConfirm} disabled={!canConfirm}>
            Confirm move
          </button>
          <button onClick={clear}>Cancel</button>
          {blockedHint && <span style={{ color: "#e6a23b" }}>{blockedHint}</span>}
          {!blockedHint && endSquareOccupied && (
            <span style={{ color: "#e6a23b" }}>can't end the move on an occupied square</span>
          )}
        </div>
      )}
    </div>
  );
}
