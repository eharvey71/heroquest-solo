import { useState } from "react";
import { createGame, generateQuest } from "../lib/functionsClient";
import { useQuestMap } from "../lib/useQuestMap";

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
  // Which of the 4 classic hero cards are actually in play -- id stays
  // pinned to the class (barbarian/dwarf/elf/wizard) since that's what
  // matters for stairway-footprint placement order; only the display
  // name is player-editable.
  const [selectedHeroes, setSelectedHeroes] = useState<Set<string>>(new Set(CLASSIC_HEROES.map((h) => h.id)));
  const [heroNames, setHeroNames] = useState<Record<string, string>>(
    Object.fromEntries(CLASSIC_HEROES.map((h) => [h.id, h.name]))
  );
  const [difficulty, setDifficulty] = useState<"standard" | "hard">("standard");
  const [size, setSize] = useState<"short" | "full">("full");
  const [theme, setTheme] = useState("");

  const [questId, setQuestId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { narrative } = useQuestMap(questId ?? undefined);

  const heroCount = selectedHeroes.size;

  const toggleHero = (id: string) => {
    setSelectedHeroes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleGenerateQuest = async () => {
    if (heroCount < 1 || heroCount > 4) return;
    setBusy(true);
    setError(null);
    try {
      const res = await generateQuest({
        heroCount: heroCount as 1 | 2 | 3 | 4,
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
      const heroes = CLASSIC_HEROES.filter((h) => selectedHeroes.has(h.id)).map((h) => ({
        id: h.id,
        name: heroNames[h.id] || h.name,
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
        <div>
          Heroes in play:{" "}
          {CLASSIC_HEROES.map((h) => (
            <label key={h.id} style={{ marginRight: 12 }}>
              <input type="checkbox" checked={selectedHeroes.has(h.id)} onChange={() => toggleHero(h.id)} /> {h.name}
            </label>
          ))}
          {heroCount === 0 && <span style={{ color: "#e66" }}> pick at least one</span>}
        </div>
        <div style={{ marginTop: 8 }}>
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
        </div>
        <p className="hint" style={{ maxWidth: 500 }}>
          Short size aims for a single sitting (fewer rooms, a shorter map to clear); full size is a
          longer, full-map quest matching the scope of the official quest book adventures.
        </p>
        <div>
          <button onClick={handleGenerateQuest} disabled={busy || heroCount < 1}>
            {busy && !questId ? "Generating..." : "Generate Quest"}
          </button>
        </div>
      </fieldset>

      {questId && (
        <div style={{ marginTop: 16 }}>
          <p>
            Quest ready: <code>{questId}</code>
          </p>
          {narrative ? (
            <div style={{ maxWidth: 600, marginBottom: 12 }}>
              <h3>{narrative.title}</h3>
              <p style={{ fontStyle: "italic", color: "#c9bfa0" }}>{narrative.backstory}</p>
              {narrative.objective && (
                <p>
                  <strong>Objective:</strong> {narrative.objective}
                </p>
              )}
              <p className="hint">
                This is auto-generated -- read it aloud at the table when you start, nothing else to fill in.
              </p>
            </div>
          ) : (
            <p className="hint">Loading quest story...</p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxWidth: 300 }}>
            {CLASSIC_HEROES.filter((h) => selectedHeroes.has(h.id)).map((h) => (
              <label key={h.id}>
                {h.name}'s name:{" "}
                <input
                  value={heroNames[h.id]}
                  onChange={(e) => setHeroNames((prev) => ({ ...prev, [h.id]: e.target.value }))}
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
