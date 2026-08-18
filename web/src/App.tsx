import { useEffect, useState } from "react";
import { GameSetup } from "./components/GameSetup";
import { GameView } from "./components/GameView";
import { ensureSignedIn } from "./lib/firebase";
import "./App.css";

const GAME_ID_STORAGE_KEY = "heroquest-zargon-game-id";

function App() {
  const [signedIn, setSignedIn] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [gameId, setGameId] = useState<string | null>(() => localStorage.getItem(GAME_ID_STORAGE_KEY));

  useEffect(() => {
    ensureSignedIn()
      .then(() => setSignedIn(true))
      .catch((e) => setAuthError(e instanceof Error ? e.message : String(e)));
  }, []);

  const handleGameCreated = (id: string) => {
    localStorage.setItem(GAME_ID_STORAGE_KEY, id);
    setGameId(id);
  };

  const handleNewQuest = () => {
    localStorage.removeItem(GAME_ID_STORAGE_KEY);
    setGameId(null);
  };

  return (
    <div className="app">
      <h1>HeroQuest Zargon</h1>

      {authError && <p style={{ color: "#e66" }}>Sign-in failed: {authError}</p>}
      {!signedIn && !authError && <p className="hint">Signing in...</p>}

      {signedIn && !gameId && <GameSetup onGameCreated={handleGameCreated} />}

      {signedIn && gameId && (
        <>
          <GameView gameId={gameId} />
          <p style={{ marginTop: 16 }}>
            <button onClick={handleNewQuest}>Start a different quest</button>
          </p>
        </>
      )}
    </div>
  );
}

export default App;
