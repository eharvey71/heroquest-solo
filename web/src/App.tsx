import { useEffect, useState } from "react";
import type { User } from "firebase/auth";
import { GameSetup } from "./components/GameSetup";
import { GameView } from "./components/GameView";
import { signInWithGoogle, signOut, verifyOwnership, watchUser } from "./lib/firebase";
import "./App.css";

const GAME_ID_STORAGE_KEY = "heroquest-zargon-game-id";

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [ownership, setOwnership] = useState<"checking" | "owner" | "denied">("checking");
  const [checkingSession, setCheckingSession] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [gameId, setGameId] = useState<string | null>(() => localStorage.getItem(GAME_ID_STORAGE_KEY));

  useEffect(
    () =>
      watchUser((signedIn) => {
        setUser(signedIn);
        setCheckingSession(false);
        if (!signedIn) {
          setOwnership("checking");
          return;
        }
        // Claims the app if it is unclaimed, then proves ownership by
        // reading a document only the owner may read.
        setOwnership("checking");
        void verifyOwnership(signedIn).then((owner) => setOwnership(owner ? "owner" : "denied"));
      }),
    []
  );

  const handleSignIn = async () => {
    setAuthError(null);
    try {
      await signInWithGoogle();
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleOpenGame = (id: string) => {
    localStorage.setItem(GAME_ID_STORAGE_KEY, id);
    setGameId(id);
  };

  const handleLeaveGame = () => {
    localStorage.removeItem(GAME_ID_STORAGE_KEY);
    setGameId(null);
  };

  return (
    <div className="app">
      {/* App chrome only: the brand, the way back to the quest list,
          the account. Everything about the game in progress -- turn,
          Story, Journal, Undo, game id -- is GameView's own game bar,
          the row beneath this one. They shared this row once and it
          read as one undifferentiated run of buttons. */}
      <div className="app-header">
        <div className="header-left">
          <h1>HeroQuest Zargon</h1>
          {user && gameId && ownership === "owner" && (
            <button className="quiet" onClick={handleLeaveGame}>
              &larr; Quests &amp; games
            </button>
          )}
        </div>
        {user && (
          <span className="hint header-account">
            {user.email ?? "signed in"}
            <button
              className="quiet"
              onClick={() => {
                localStorage.removeItem(GAME_ID_STORAGE_KEY);
                setGameId(null);
                void signOut();
              }}
            >
              Sign out
            </button>
          </span>
        )}
      </div>

      {authError && <p style={{ color: "#e66" }}>Sign-in failed: {authError}</p>}
      {checkingSession && <p className="hint">Checking your session...</p>}

      {!checkingSession && !user && (
        <div style={{ maxWidth: 520 }}>
          <p>This dungeon belongs to one Zargon. Sign in to take your turn.</p>
          <button onClick={handleSignIn}>Sign in with Google</button>
        </div>
      )}

      {user && ownership === "checking" && <p className="hint">Checking your account...</p>}

      {user && ownership === "denied" && (
        <div style={{ maxWidth: 520 }}>
          <p style={{ color: "#e6a23b" }}>
            This app already belongs to another account. Sign out and try the account that set it up.
          </p>
        </div>
      )}

      {user && ownership === "owner" && !gameId && <GameSetup onOpenGame={handleOpenGame} />}

      {user && ownership === "owner" && gameId && <GameView gameId={gameId} />}
    </div>
  );
}

export default App;
