import { doc, onSnapshot } from "firebase/firestore";
import { useEffect, useState } from "react";
import {
  deleteGameForever,
  deleteQuestStackForever,
  deleteRemovedForever,
  findRemoved,
  setGameArchived,
  setQuestStackArchived,
} from "../lib/archive";
import { db } from "../lib/firebase";
import {
  createGame,
  describeGenerationError,
  generateQuest,
  generateSideQuests,
  type PlayMode,
} from "../lib/functionsClient";
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

function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

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
    quest.mode === "expanded"
      ? quest.sideQuestsStatus === "ready"
        ? "expanded (side quests)"
        : "expanded (side quests not written yet)"
      : null,
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
  /** The variant a NEW quest is generated with (design/side-quests-
   * design.md section 0). Traditional is exactly today's game. */
  const [mode, setMode] = useState<PlayMode>("traditional");
  /** How a game on an expanded quest is played -- a replay can go
   * traditional. Ignored (forced traditional) on a traditional quest. */
  const [playMode, setPlayMode] = useState<PlayMode>("expanded");
  const [theme, setTheme] = useState("");
  // A finished, chronicled game this new quest continues from -- "" means
  // standalone (the common case). See generator/prompt.py's CAMPAIGN
  // CONTINUITY section: the chronicle becomes context the LLM may thread
  // into the new backstory, never a hard requirement.
  const [continuesFromGameId, setContinuesFromGameId] = useState("");

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
  // Live status of a generation in progress. The browser picks a job id,
  // sends it with the call, and listens to generationJobs/{jobId}, which
  // the backend writes each stage to (main._JobProgress) -- a callable
  // is one long request the client can't otherwise see inside.
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<{ stage: string; detail: string } | null>(null);
  // 2 for a full expanded generation (quest, then scenes) so the status
  // line can say which step is running; 1 for anything else.
  const [jobSteps, setJobSteps] = useState<1 | 2>(1);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  // The side quests are a second call after the quest is saved, so a
  // failure there leaves a usable (traditional) quest and a retry.
  const [sideQuestsBusy, setSideQuestsBusy] = useState(false);
  const [sideQuestError, setSideQuestError] = useState<string | null>(null);
  const [questVersion, setQuestVersion] = useState(0);
  const {
    narrative,
    mode: questMode,
    requestedMode: questRequestedMode,
    sideQuestsStatus: questSideQuestsStatus,
    sideQuestErrors: questSideQuestErrors,
    sideQuests: questSideQuests,
  } = useQuestMap(questId ?? undefined, questVersion);

  useEffect(() => {
    if (!jobId) return;
    const unsubscribe = onSnapshot(
      doc(db, "generationJobs", jobId),
      (snap) => {
        const data = snap.data() as { stage?: string; detail?: string } | undefined;
        if (data?.stage) setJobStatus({ stage: data.stage, detail: data.detail ?? "" });
      },
      () => {
        // A rules or network hiccup on the status doc must never look
        // like a generation failure -- the call itself reports that.
      }
    );
    return unsubscribe;
  }, [jobId]);

  const working = busy || sideQuestsBusy;
  useEffect(() => {
    if (!working || startedAt === null) return;
    setElapsed(Date.now() - startedAt);
    const timer = setInterval(() => setElapsed(Date.now() - startedAt), 1000);
    return () => clearInterval(timer);
  }, [working, startedAt]);
  const library = useLibrary(refreshKey);
  // A removed game shouldn't offer itself as a campaign predecessor --
  // it's meant to be out of the way, not still steering new quests.
  const continuableGames = library.games.filter((g) => g.hasChronicle && !g.archived);

  // Quests & Games list management: one removed game or "remove the
  // entire stack" quest+games action never deletes anything, only
  // hides it -- toggled back with the same button once "Show removed"
  // is on. See lib/archive.ts.
  const [showArchived, setShowArchived] = useState(false);
  const [archiveBusyId, setArchiveBusyId] = useState<string | null>(null);

  const heroCount = selectedHeroes.size;

  const toggleHero = (id: string) => {
    setSelectedHeroes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const startJob = (steps: 1 | 2) => {
    const id = crypto.randomUUID();
    setJobId(id);
    setJobSteps(steps);
    setJobStatus({ stage: "starting", detail: "Contacting the generator…" });
    setStartedAt(Date.now());
    setElapsed(0);
    return id;
  };

  const writeSideQuests = async (forQuestId: string, forJobId: string) => {
    setSideQuestsBusy(true);
    setSideQuestError(null);
    try {
      await generateSideQuests({ questId: forQuestId, jobId: forJobId });
    } catch (e) {
      setSideQuestError(describeGenerationError(e));
    } finally {
      setSideQuestsBusy(false);
      // Re-read the quest either way: it now carries the scenes, or the
      // failed status and its errors.
      setQuestVersion((v) => v + 1);
      setRefreshKey((k) => k + 1);
    }
  };

  const handleGenerateQuest = async () => {
    if (heroCount < 1 || heroCount > 4) return;
    setBusy(true);
    setError(null);
    setSideQuestError(null);
    const newJobId = startJob(mode === "expanded" ? 2 : 1);
    let pending: { questId: string } | null = null;
    try {
      const res = await generateQuest({
        heroCount: heroCount as 1 | 2 | 3 | 4,
        difficulty,
        size,
        mode,
        jobId: newJobId,
        ...(theme.trim() ? { theme: theme.trim() } : {}),
        ...(continuesFromGameId ? { continuesFromGameId } : {}),
      });
      setQuestId(res.questId);
      setQuestHeroCount(heroCount);
      setRefreshKey((k) => k + 1);
      if (res.sideQuestsPending) pending = { questId: res.questId };
    } catch (e) {
      setError(describeGenerationError(e));
    } finally {
      setBusy(false);
    }
    // Outside the try: the quest is saved whatever happens next.
    if (pending) await writeSideQuests(pending.questId, newJobId);
  };

  const handleRetrySideQuests = async () => {
    if (!questId) return;
    const newJobId = startJob(1);
    await writeSideQuests(questId, newJobId);
  };

  const handleReplayQuest = (quest: QuestSummary) => {
    setError(null);
    setSideQuestError(null);
    setJobStatus(null);
    setStartedAt(null);
    setQuestId(quest.id);
    setQuestHeroCount(quest.heroCount);
    if (quest.difficulty === "standard" || quest.difficulty === "hard") setDifficulty(quest.difficulty);
    if (quest.size === "short" || quest.size === "full") setSize(quest.size);
    setTheme(quest.theme ?? "");
    setMode(quest.mode);
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
      const res = await createGame({
        questId,
        heroes,
        spellbooks,
        mode: questMode === "expanded" ? playMode : "traditional",
      });
      onOpenGame(res.gameId);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleToggleQuestArchived = async (quest: QuestSummary) => {
    setArchiveBusyId(quest.id);
    setError(null);
    try {
      await setQuestStackArchived(quest.id, !quest.archived);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setArchiveBusyId(null);
    }
  };

  // Permanent deletion is offered only on rows already removed, and
  // archive.ts refuses anything else server-side-of-the-click too.
  const runDelete = async (busyId: string, work: () => Promise<unknown>) => {
    setArchiveBusyId(busyId);
    setError(null);
    try {
      await work();
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setArchiveBusyId(null);
    }
  };

  const handleDeleteQuest = (quest: QuestSummary) => {
    if (!window.confirm(`Delete "${quest.title}" and every removed game played on it, permanently?`)) return;
    void runDelete(quest.id, () => deleteQuestStackForever(quest.id));
  };

  const handleDeleteGame = (game: GameSummary) => {
    if (!window.confirm("Delete this game and its undo history, permanently?")) return;
    void runDelete(game.id, () => deleteGameForever(game.id));
  };

  const handleDeleteAllRemoved = () =>
    runDelete("__all__", async () => {
      const items = await findRemoved();
      if (items.questIds.length === 0 && items.gameIds.length === 0) {
        throw new Error("Nothing is removed.");
      }
      const what = `${items.questIds.length} removed quest(s) and ${items.gameIds.length} removed game(s)`;
      if (!window.confirm(`Delete ${what} permanently? This cannot be undone.`)) return;
      await deleteRemovedForever(items);
    });

  const handleToggleGameArchived = async (game: GameSummary) => {
    setArchiveBusyId(game.id);
    setError(null);
    try {
      await setGameArchived(game.id, !game.archived);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setArchiveBusyId(null);
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
        <div style={{ marginTop: 8 }}>
          Variant:{" "}
          <label style={{ marginRight: 12 }}>
            <input type="radio" name="variant" checked={mode === "traditional"} onChange={() => setMode("traditional")} />{" "}
            Traditional
          </label>
          <label>
            <input type="radio" name="variant" checked={mode === "expanded"} onChange={() => setMode("expanded")} />{" "}
            Expanded: side quests
          </label>
        </div>
        {continuableGames.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <label>
              Continue from (optional):{" "}
              <select value={continuesFromGameId} onChange={(e) => setContinuesFromGameId(e.target.value)}>
                <option value="">Standalone quest</option>
                {continuableGames.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.questTitle ?? g.questId ?? g.id} ({g.status === "complete" ? "won" : "lost"})
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        <p className="hint" style={{ maxWidth: 500 }}>
          Short size aims for a single sitting (fewer rooms, a shorter map to clear); full size is a
          longer, full-map quest matching the scope of the official quest book adventures.
          {mode === "expanded" && (
            <>
              {" "}
              Expanded adds one or two short optional side quests written from the same story &mdash; played in
              the app in 10-15 minutes each &mdash; and, one time in three, a required one the finale depends on.
              Generation takes a little longer.
            </>
          )}
          {continuableGames.length > 0 && (
            <>
              {" "}
              Picking a previous game hands its chronicle to the generator as history it may reference
              &mdash; a villain who escaped, an artifact recovered &mdash; never a requirement.
            </>
          )}
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <button onClick={handleGenerateQuest} disabled={working || heroCount < 1}>
            {busy ? "Generating..." : "Generate Quest"}
          </button>
          {jobStatus && (
            <span className="gen-status" aria-live="polite">
              {working && <span className="gen-spinner" aria-hidden />}
              <span className="gen-text">
                {jobSteps === 2 && (jobStatus.stage.includes("side_quest") ? "Step 2 of 2: " : "Step 1 of 2: ")}
                {jobStatus.detail || jobStatus.stage}
              </span>
              {startedAt !== null && working && <span className="hint gen-clock">{formatElapsed(elapsed)}</span>}
            </span>
          )}
        </div>
      </fieldset>

      {questId && (
        <div style={{ marginTop: 16 }}>
          <p>
            Quest ready: <code>{questId}</code>{" "}
            <button onClick={() => { setQuestId(null); setQuestHeroCount(null); setJobStatus(null); setSideQuestError(null); }} disabled={working}>
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
          {questRequestedMode === "expanded" && questSideQuestsStatus !== "ready" && (
            <div className="panel" style={{ maxWidth: 520, marginBottom: 12 }}>
              <p className="panel-title">Side quests</p>
              <div className="panel-stack">
                {sideQuestsBusy ? (
                  <span className="hint">Being written now &mdash; see the status above.</span>
                ) : (
                  <>
                    <span className="hint">
                      {questSideQuestsStatus === "failed"
                        ? "The generator's scenes failed the checks. The quest itself is fine and can be played traditional now, or try the side quests again."
                        : "Not written yet. The quest can be played traditional now, or write the side quests first."}
                    </span>
                    {(sideQuestError || questSideQuestErrors.length > 0) && (
                      <span style={{ color: "#e6a23b" }}>
                        {sideQuestError ?? questSideQuestErrors.slice(0, 2).join("; ")}
                      </span>
                    )}
                    <div className="panel-row">
                      <button onClick={handleRetrySideQuests} disabled={working}>
                        {questSideQuestsStatus === "failed" ? "Try the side quests again" : "Write the side quests"}
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
          {questMode === "expanded" && (
            <div className="panel" style={{ maxWidth: 520, marginBottom: 12 }}>
              <p className="panel-title">Play this quest as</p>
              <div className="panel-row">
                <label style={{ marginRight: 12 }}>
                  <input type="radio" name="playMode" checked={playMode === "expanded"} onChange={() => setPlayMode("expanded")} />{" "}
                  Expanded &mdash; {questSideQuests.length} side quest{questSideQuests.length === 1 ? "" : "s"} written for it
                </label>
                <label>
                  <input type="radio" name="playMode" checked={playMode === "traditional"} onChange={() => setPlayMode("traditional")} />{" "}
                  Traditional &mdash; the dungeon only
                </label>
              </div>
            </div>
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
            disabled={working || heroCount < 1 || (selectedHeroes.has("wizard") && wizardElements.length !== 3)}
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

      <h2>Quests &amp; Games</h2>
      <p className="hint" style={{ maxWidth: 600 }}>
        A quest is a fixed map and story; each game beneath it is one playthrough of it, fog of war,
        traps and monsters all its own. Replaying a quest starts a fresh game on the same dungeon.
      </p>
      <label className="hint" style={{ display: "block", marginBottom: 8 }}>
        <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show
        removed
      </label>
      {showArchived && (
        <p className="hint" style={{ margin: "0 0 10px" }}>
          Removed rows are faded. Restore brings one back; Delete is permanent.{" "}
          <button className="quiet" disabled={archiveBusyId !== null} onClick={() => void handleDeleteAllRemoved()}>
            Delete all removed
          </button>
        </p>
      )}
      {library.loading && <p className="hint">Loading...</p>}
      {library.error && <p style={{ color: "#e66" }}>Couldn't load past games: {library.error}</p>}

      {(() => {
        const questById = new Map(library.quests.map((q) => [q.id, q]));
        const visibleQuests = library.quests.filter((q) => showArchived || !q.archived);
        const gamesForQuest = (id: string) =>
          library.games
            .filter((g) => g.questId === id && (showArchived || !g.archived))
            .sort((a, b) => (b.lastActionAt?.getTime() ?? 0) - (a.lastActionAt?.getTime() ?? 0));
        // A game whose quest fell off the most-recent-25 page it's own
        // record still identifies it by title/id, so it's still usable
        // -- it just can't be grouped under a quest row we don't have.
        const orphanGames = library.games.filter(
          (g) => (showArchived || !g.archived) && (!g.questId || !questById.has(g.questId))
        );

        if (!library.loading && visibleQuests.length === 0 && orphanGames.length === 0) {
          return <p className="hint">{showArchived ? "Nothing removed." : "No quests generated yet."}</p>;
        }

        return (
          <>
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {visibleQuests.map((quest) => {
                const games = gamesForQuest(quest.id);
                return (
                  <li
                    key={quest.id}
                    className="panel"
                    style={{ marginBottom: 10, opacity: quest.archived ? 0.55 : 1 }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <button onClick={() => handleReplayQuest(quest)} disabled={busy || questId === quest.id}>
                          {questId === quest.id ? "Selected" : "Play again"}
                        </button>{" "}
                        <strong>{quest.title}</strong>{" "}
                        <span className="hint">
                          {questLine(quest)} &mdash; generated {formatWhen(quest.createdAt)}
                        </span>
                      </div>
                      <button
                        style={{ flexShrink: 0 }}
                        disabled={archiveBusyId === quest.id}
                        onClick={() => handleToggleQuestArchived(quest)}
                      >
                        {quest.archived ? "Restore" : "Remove"}
                      </button>
                      {quest.archived && (
                        <button
                          className="danger"
                          style={{ flexShrink: 0 }}
                          disabled={archiveBusyId !== null}
                          onClick={() => handleDeleteQuest(quest)}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                    {games.length === 0 ? (
                      <p className="hint" style={{ margin: "6px 0 0 20px" }}>
                        Not played yet.
                      </p>
                    ) : (
                      <ul style={{ listStyle: "none", padding: 0, margin: "6px 0 0 20px" }}>
                        {games.map((game) => (
                          <li key={game.id} style={{ marginBottom: 4, opacity: game.archived ? 0.55 : 1 }}>
                            <button onClick={() => onOpenGame(game.id)} disabled={busy}>
                              Resume
                            </button>{" "}
                            <span className="hint">
                              {gameLine(game)} &mdash; started {formatWhen(game.createdAt)}, last played{" "}
                              {formatWhen(game.lastActionAt)}
                            </span>{" "}
                            <button
                              disabled={archiveBusyId === game.id}
                              onClick={() => handleToggleGameArchived(game)}
                            >
                              {game.archived ? "Restore" : "Remove"}
                            </button>
                            {game.archived && (
                              <>
                                {" "}
                                <button className="danger" disabled={archiveBusyId !== null} onClick={() => handleDeleteGame(game)}>
                                  Delete
                                </button>
                              </>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>

            {orphanGames.length > 0 && (
              <>
                <h3 style={{ marginTop: 16 }}>Other games</h3>
                <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {orphanGames.map((game) => (
                    <li key={game.id} style={{ marginBottom: 8, opacity: game.archived ? 0.55 : 1 }}>
                      <button onClick={() => onOpenGame(game.id)} disabled={busy}>
                        Resume
                      </button>{" "}
                      <strong>{game.questTitle ?? game.questId ?? "(quest unknown)"}</strong>{" "}
                      <span className="hint">
                        {gameLine(game)} &mdash; started {formatWhen(game.createdAt)}, last played{" "}
                        {formatWhen(game.lastActionAt)}
                      </span>{" "}
                      <button disabled={archiveBusyId === game.id} onClick={() => handleToggleGameArchived(game)}>
                        {game.archived ? "Restore" : "Remove"}
                      </button>
                      {game.archived && (
                        <>
                          {" "}
                          <button className="danger" disabled={archiveBusyId !== null} onClick={() => handleDeleteGame(game)}>
                            Delete
                          </button>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        );
      })()}
    </div>
  );
}
