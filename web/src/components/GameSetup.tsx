import { useState } from "react";
import { createGame, generateQuest } from "../lib/functionsClient";
import { SPELL_ELEMENTS } from "../data/heroSpells";
import { useLibrary, type GameSummary, type QuestSummary } from "../lib/useLibrary";
import { useQuestMap } from "../lib/useQuestMap";

interface GameSetupProps {
  onOpenGame: (gameId: string) => void;
}

const CLASSIC_HEROES = [
  { id: "barbarian", name: "Barbarian" },
  { id: "dwarf", name: "Dwarf" },
  { id: "elf", name: "Elf" },
  { id: "wizard", name: "Wizard" },
];

function formatWhen(date: Date | null): string {
  if (!date) return "just now";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    " " + date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function questLine(quest: QuestSummary): string {
  const parts = [
    quest.heroCount ? `${quest.heroCount} hero${quest.heroCount === 1 ? "" : "es"}` : null,
    quest.size,
    quest.difficulty,
    quest.theme,
  ].filter(Boolean);
  return parts.join(" / ");
}

function gameLine(game: GameSummary): string {
  const state =
    game.status === "complete"
      ? "finished"
      : game.objectiveComplete
        ? `turn ${game.turn}, heading back to the stairway`
        : `turn ${game.turn}`;
  return [game.heroNames.join(", "), state].filter(Boolean).join(" -- ");
}

export function GameSetup({ onOpenGame }: GameSetupProps) {
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

  // Which spell elements each caster took. The Wizard picks three, the
  // Elf one of what's left -- one physical set of three cards per
  // element, so they can't overlap (functions/engine/hero_spells.py).
  const [wizardElements, setWizardElements] = useState<string[]>(["Fire", "Earth", "Air"]);
  const [elfElement, setElfElement] = useState<string>("Water");

  const [questId, setQuestId] = useState<string | null>(null);
  // The hero count the chosen quest's monster budget was priced for
  // (CLAUDE.md's Balance system). Known locally for a quest generated in
  // this session, read off generationParams for one picked from the list.
  const [questHeroCount, setQuestHeroCount] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const { narrative } = useQuestMap(questId ?? undefined);
  const library = useLibrary(refreshKey);

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
      setQuestHeroCount(heroCount);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleReplayQuest = (quest: QuestSummary) => {
    setError(null);
    setQuestId(quest.id);
    setQuestHeroCount(quest.heroCount);
    if (quest.difficulty === "standard" || quest.difficulty === "hard") setDifficulty(quest.difficulty);
    if (quest.size === "short" || quest.size === "full") setSize(quest.size);
    setTheme(quest.theme ?? "");
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
      const spellbooks: Record<string, string[]> = {};
      if (selectedHeroes.has("wizard")) spellbooks.wizard = wizardElements;
      if (selectedHeroes.has("elf")) spellbooks.elf = [elfElement];
      const res = await createGame({ questId, heroes, spellbooks });
      onOpenGame(res.gameId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="setup">
      <h2>Start a Quest</h2>

      <fieldset disabled={busy}>
        <div>
          Heroes in play:{" "}
          {CLASSIC_HEROES.map((h) => (
            <label key={h.id} style={{ marginRight: 12 }}>
              <input type="checkbox" checked={selectedHeroes.has(h.id)} onChange={() => toggleHero(h.id)} /> {h.name}
            </label>
          ))}
          {heroCount === 0 && <span style={{ color: "#e66" }}> pick at least one</span>}
        </div>
      </fieldset>

      <fieldset disabled={busy || questId !== null}>
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
            Quest ready: <code>{questId}</code>{" "}
            <button onClick={() => { setQuestId(null); setQuestHeroCount(null); }} disabled={busy}>
              Choose a different quest
            </button>
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
          {questHeroCount !== null && questHeroCount !== heroCount && (
            <p style={{ color: "#e6a23b", maxWidth: 600 }}>
              This quest's monsters were budgeted for {questHeroCount} hero{questHeroCount === 1 ? "" : "es"}, and
              you have {heroCount} selected. It will still run -- it just won't be balanced.
            </p>
          )}
          {(selectedHeroes.has("wizard") || selectedHeroes.has("elf")) && (
            <div className="panel" style={{ maxWidth: 520, marginBottom: 12 }}>
              <p className="panel-title">Spell cards</p>
              <div className="panel-stack">
                <span className="hint">
                  The Wizard takes three elements, the Elf one of what&apos;s left &mdash; three cards each.
                </span>
                {selectedHeroes.has("wizard") && (
                  <div className="panel-row">
                    <span style={{ width: 70 }}>Wizard</span>
                    {SPELL_ELEMENTS.map((element) => {
                      const taken = wizardElements.includes(element);
                      const heldByElf = selectedHeroes.has("elf") && elfElement === element;
                      return (
                        <label key={element} style={{ opacity: heldByElf ? 0.4 : 1 }}>
                          <input
                            type="checkbox"
                            checked={taken}
                            disabled={heldByElf || (!taken && wizardElements.length >= 3)}
                            onChange={() =>
                              setWizardElements((prev) =>
                                prev.includes(element)
                                  ? prev.filter((e) => e !== element)
                                  : [...prev, element]
                              )
                            }
                          />{" "}
                          {element}
                        </label>
                      );
                    })}
                    {wizardElements.length !== 3 && (
                      <span style={{ color: "#e6a23b" }}>pick {3 - wizardElements.length} more</span>
                    )}
                  </div>
                )}
                {selectedHeroes.has("elf") && (
                  <div className="panel-row">
                    <span style={{ width: 70 }}>Elf</span>
                    <select value={elfElement} onChange={(e) => setElfElement(e.target.value)}>
                      {SPELL_ELEMENTS.filter(
                        (element) => !selectedHeroes.has("wizard") || !wizardElements.includes(element)
                      ).map((element) => (
                        <option key={element} value={element}>
                          {element}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>
            </div>
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
          <button
            style={{ marginTop: 8 }}
            onClick={handleCreateGame}
            disabled={busy || heroCount < 1 || (selectedHeroes.has("wizard") && wizardElements.length !== 3)}
          >
            {busy ? "Creating..." : "Create Game"}
          </button>
        </div>
      )}

      {error && (
        <p style={{ color: "#e66" }}>
          Error: {error}
        </p>
      )}

      <hr style={{ margin: "24px 0", borderColor: "#333" }} />

      <h2>Games</h2>
      {library.loading && <p className="hint">Loading...</p>}
      {library.error && <p style={{ color: "#e66" }}>Couldn't load past games: {library.error}</p>}
      {!library.loading && library.games.length === 0 && <p className="hint">No games yet.</p>}
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {library.games.map((game) => (
          <li key={game.id} style={{ marginBottom: 8 }}>
            <button onClick={() => onOpenGame(game.id)} disabled={busy}>
              Resume
            </button>{" "}
            <strong>{game.questTitle ?? game.questId ?? "(quest unknown)"}</strong>{" "}
            <span className="hint">
              {gameLine(game)} &mdash; started {formatWhen(game.createdAt)}
            </span>
          </li>
        ))}
      </ul>

      <h2 style={{ marginTop: 24 }}>Quests</h2>
      <p className="hint" style={{ maxWidth: 600 }}>
        A quest is a fixed map and story -- replaying one starts a brand new game on the same dungeon,
        with fog of war, traps and monsters all reset.
      </p>
      {!library.loading && library.quests.length === 0 && <p className="hint">No quests generated yet.</p>}
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {library.quests.map((quest) => (
          <li key={quest.id} style={{ marginBottom: 8 }}>
            <button onClick={() => handleReplayQuest(quest)} disabled={busy || questId === quest.id}>
              {questId === quest.id ? "Selected" : "Play again"}
            </button>{" "}
            <strong>{quest.title}</strong>{" "}
            <span className="hint">
              {questLine(quest)} &mdash; generated {formatWhen(quest.createdAt)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
