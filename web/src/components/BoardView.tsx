import { useCallback, useMemo, useRef } from "react";
import { board as staticBoard, type Coord, squareKey } from "../lib/board";
import { revealedSquareKeys, type GameState } from "../lib/gameState";
import { BoardTerrain } from "./BoardTerrain";
import { PathOverlay } from "./PathOverlay";
import { Tokens } from "./Tokens";
import { usePathInput } from "../hooks/usePathInput";

interface BoardViewProps {
  gameState: GameState;
  cellSize?: number;
  onConfirmMove?: (heroId: string, path: Coord[]) => void;
}

export function BoardView({ gameState, cellSize = 28, onConfirmMove }: BoardViewProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const lastCoordKeyRef = useRef<string | null>(null);

  const revealed = useMemo(() => revealedSquareKeys(staticBoard, gameState.revealed), [gameState.revealed]);

  const { selectedHeroId, path, isDragging, selectHero, extendTo, startDragging, stopDragging, clear, canConfirm } =
    usePathInput({ board: staticBoard, heroes: gameState.heroes, monsters: gameState.monsters });

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
      } else if (selectedHeroId) {
        extendTo(coord);
      } else {
        return; // no active path and no hero clicked -- nothing to do
      }
      lastCoordKeyRef.current = key;
      startDragging();
    },
    [coordFromEvent, gameState.heroes, selectHero, selectedHeroId, extendTo, startDragging]
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent<SVGSVGElement>) => {
      if (!isDragging) return;
      const coord = coordFromEvent(e);
      if (!coord) return;
      const key = squareKey(coord[0], coord[1]);
      if (key === lastCoordKeyRef.current) return;
      lastCoordKeyRef.current = key;
      extendTo(coord);
    },
    [isDragging, coordFromEvent, extendTo]
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
        style={{ maxWidth: staticBoard.width * cellSize, background: "#111", touchAction: "none" }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      >
        <BoardTerrain board={staticBoard} cellSize={cellSize} revealed={revealed} />
        <PathOverlay cellSize={cellSize} path={path} />
        <Tokens
          cellSize={cellSize}
          heroes={gameState.heroes}
          monsters={gameState.monsters}
          revealed={revealed}
          selectedHeroId={selectedHeroId ?? undefined}
        />
      </svg>
      {selectedHero && (
        <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
          <span>
            Moving {selectedHero.name}: {Math.max(path.length - 1, 0)} step(s)
          </span>
          <button onClick={handleConfirm} disabled={!canConfirm}>
            Confirm move
          </button>
          <button onClick={clear}>Cancel</button>
        </div>
      )}
    </div>
  );
}
