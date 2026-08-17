import { useState } from "react";
import { BoardView } from "./components/BoardView";
import type { Coord } from "./lib/board";
import { mockGameState } from "./lib/mockGameState";
import "./App.css";

function App() {
  const [lastMove, setLastMove] = useState<string | null>(null);

  const handleConfirmMove = (heroId: string, path: Coord[]) => {
    // No Zargon engine yet (Task 5) -- this just proves the path reaches
    // the caller. Real wiring lands when movement resolution exists.
    setLastMove(`${heroId}: ${path.map(([x, y]) => `(${x},${y})`).join(" -> ")}`);
  };

  return (
    <div className="app">
      <h1>HeroQuest Zargon</h1>
      <p className="hint">
        Click a hero token, then click or drag across adjacent squares to trace a move.
      </p>
      <BoardView gameState={mockGameState} onConfirmMove={handleConfirmMove} />
      {lastMove && (
        <p className="last-move">
          Last confirmed move: <code>{lastMove}</code>
        </p>
      )}
    </div>
  );
}

export default App;
