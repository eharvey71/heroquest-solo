import { useState } from "react";
import { createGame, generateQuest } from "../lib/functionsClient";

interface GameSetupProps {
  onGameCreated: (gameId: string) => void;
}

const CLASSIC_HEROES = [
  { id: "barbarian", name: "Barbarian" },
  { id: "dwarf", name: "Dwarf" },
  { id: "elf", name: "Elf" },
  { id: "wizard", name: "Wizard" },
];

export function GameSetup({ onGameCreated }: GameSetupProps) {
  const [heroCount, setHeroCount] = useState<1 | 2 | 3 | 4>(4);
  const [difficulty, setDifficulty] = useState<"standard" | "hard">("standard");
  const [size, setSize] = useState<"short" | "full">("full");
  const [theme, setTheme] = useState("");
  const [heroNames, setHeroNames] = useState<string[]>(CLASSIC_HEROES.slice(0, 4).map((h) => h.name));

  const [questId, setQuestId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleHeroCountChange = (n: 1 | 2 | 3 | 4) => {
    setHeroCount(n);
    setHeroNames((prev) => {
      const next = CLASSIC_HEROES.slice(0, n).map((h) => h.name);
      for (let i = 0; i < Math.min(n, prev.length); i++) next[i] = prev[i];
      return next;
    });
  };

  const handleGenerateQuest = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await generateQuest({
        heroCount,
        difficulty,
        size,
        ...(theme.trim() ? { theme: theme.trim() } : {}),
      });
      setQuestId(res.questId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleCreateGame = async () => {
    if (!questId) return;
    setBusy(true);
    setError(null);
    try {
      const heroes = heroNames.slice(0, heroCount).map((name, i) => ({
        id: CLASSIC_HEROES[i]?.id ?? `hero${i}`,
        name,
      }));
      const res = await createGame({ questId, heroes });
      onGameCreated(res.gameId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="setup">
      <h2>Start a Quest</h2>

      <fieldset disabled={busy || questId !== null}>
        <label>
          Heroes:{" "}
          <select value={heroCount} onChange={(e) => handleHeroCountChange(Number(e.target.value) as 1 | 2 | 3 | 4)}>
            {[1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          Difficulty:{" "}
          <select value={difficulty} onChange={(e) => setDifficulty(e.target.value as "standard" | "hard")}>
            <option value="standard">Standard</option>
            <option value="hard">Hard</option>
          </select>
        </label>{" "}
        <label>
          Size:{" "}
          <select value={size} onChange={(e) => setSize(e.target.value as "short" | "full")}>
            <option value="short">Short</option>
            <option value="full">Full</option>
          </select>
        </label>{" "}
        <label>
          Theme (optional): <input value={theme} onChange={(e) => setTheme(e.target.value)} placeholder="e.g. undead crypt" />
        </label>
        <div style={{ marginTop: 8 }}>
          <button onClick={handleGenerateQuest} disabled={busy}>
            {busy && !questId ? "Generating..." : "Generate Quest"}
          </button>
        </div>
      </fieldset>

      {questId && (
        <div style={{ marginTop: 16 }}>
          <p>
            Quest ready: <code>{questId}</code>
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxWidth: 300 }}>
            {heroNames.slice(0, heroCount).map((name, i) => (
              <label key={i}>
                Hero {i + 1}:{" "}
                <input
                  value={name}
                  onChange={(e) =>
                    setHeroNames((prev) => prev.map((n, idx) => (idx === i ? e.target.value : n)))
                  }
                />
              </label>
            ))}
          </div>
          <button style={{ marginTop: 8 }} onClick={handleCreateGame} disabled={busy}>
            {busy ? "Creating..." : "Create Game"}
          </button>
        </div>
      )}

      {error && (
        <p style={{ color: "#e66" }}>
          Error: {error}
        </p>
      )}
    </div>
  );
}
