import { useEffect, useMemo, useState } from "react";
import { board as staticBoard, CORRIDOR, type Coord, squareKey } from "../lib/board";
import {
  endTurn,
  openDoor,
  recordHeroDefense,
  resolveHeroAttack,
  resolveMovement,
  resolveZargonTurn,
  rollZargonTurnType,
  searchTrapsAndSecretDoors,
  searchTreasure,
} from "../lib/functionsClient";
import { revealedSquareKeys } from "../lib/gameState";
import { useLiveGame } from "../lib/useLiveGame";
import { type DoorState, useQuestMap } from "../lib/useQuestMap";
import { BoardView } from "./BoardView";

interface GameViewProps {
  gameId: string;
}

interface PendingDefense {
  key: string;
  heroId: string;
  heroName: string;
  skulls: number;
}

export function GameView({ gameId }: GameViewProps) {
  const { game, loading, error } = useLiveGame(gameId);

  const [heroId, setHeroId] = useState<string>("");
  const [pendingDoorId, setPendingDoorId] = useState<string | null>(null);
  const [wanderingDrawn, setWanderingDrawn] = useState(false);
  const [attackMonsterId, setAttackMonsterId] = useState<string>("");
  const [attackSkulls, setAttackSkulls] = useState(0);
  const [rolledTurn, setRolledTurn] = useState<{
    turnType: "normal" | "cunning" | "wandering";
    needsCunningPrompt: boolean;
    heroes: { id: string; name: string }[];
  } | null>(null);
  const [lowestBpHeroId, setLowestBpHeroId] = useState<string>("");
  const [pendingDefenses, setPendingDefenses] = useState<PendingDefense[]>([]);
  const [actionLog, setActionLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (game && (!heroId || !game.heroes.some((h) => h.id === heroId))) {
      setHeroId(game.heroes[0]?.id ?? "");
    }
  }, [game, heroId]);

  const pushLog = (lines: string[]) => setActionLog((prev) => [...prev, ...lines]);

  async function runAction<T>(fn: () => Promise<T>): Promise<T | null> {
    setBusy(true);
    setErrorMsg(null);
    try {
      return await fn();
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBusy(false);
    }
  }

  const enqueueDefense = (heroName: string, skulls: number) => {
    const hero = game?.heroes.find((h) => h.name === heroName);
    if (!hero) return;
    setPendingDefenses((prev) => [...prev, { key: `${hero.id}-${Date.now()}-${Math.random()}`, heroId: hero.id, heroName, skulls }]);
  };

  // Door/stairway geometry is quest-owned (fetched once); door
  // *state* is game-owned (overrides quest.doors' initial state) --
  // merge them for rendering, same precedence the backend uses (see
  // doors.py). Stairway placement never changes after quest setup.
  const { doors: questDoors, stairway, furniture, narrative } = useQuestMap(game?.questId);
  const resolvedDoors = useMemo(
    () => questDoors.map((d) => ({ ...d, state: (game?.doors?.[d.id] as DoorState | undefined) ?? d.state })),
    [questDoors, game?.doors]
  );
  const [narrativeOpen, setNarrativeOpen] = useState(false);

  if (loading) return <p>Loading game...</p>;
  if (error) return <p style={{ color: "#e66" }}>Error: {error}</p>;
  if (!game) return null;

  // Fog of war: hidden monsters must never appear in the attack list --
  // the dropdown otherwise leaks every unrevealed room's contents.
  const revealedKeys = revealedSquareKeys(staticBoard, game.revealed);
  const targetableMonsters = game.monsters.filter((m) => m.alive && revealedKeys.has(squareKey(m.pos[0], m.pos[1])));

  const activeHero = game.heroes.find((h) => h.id === heroId);
  const activeHeroArea = activeHero ? staticBoard.areaOf.get(squareKey(activeHero.pos[0], activeHero.pos[1])) : undefined;
  const activeHeroRoomId = activeHeroArea && activeHeroArea !== CORRIDOR ? activeHeroArea : null;
  const roomAlreadySearchedTreasure = activeHeroRoomId ? game.searched?.[activeHeroRoomId]?.treasure : false;
  const roomAlreadySearchedTraps = activeHeroRoomId ? game.searched?.[activeHeroRoomId]?.traps : false;

  const handleConfirmMove = async (movingHeroId: string, path: Coord[]) => {
    // result.log is already written to the live game.log by the
    // backend (see main.py's _apply_movement) -- the Firestore
    // subscription renders it a moment later, so pushing it into
    // actionLog too would just show every line twice.
    const result = await runAction(() => resolveMovement({ gameId, heroId: movingHeroId, path }));
    if (!result) return;
    for (const t of result.triggeredTraps) pushLog([`PLACE TILE: ${t.placementInstruction}`]);
    if (result.stoppedReason === "closed_door" && result.stoppedAtDoorId) {
      setPendingDoorId(result.stoppedAtDoorId);
    } else if (result.stoppedReason) {
      // A partial move with no visible explanation feels like a bug --
      // name the obstacle (closed_door has its own flow above).
      const reasons: Record<string, string> = {
        locked_door: "Movement stopped: that door won't open from here.",
        monster_blocked: "Movement stopped: a monster blocks the path.",
        blocked_square: "Movement stopped: that square is blocked (place the blocked-square tile if not already placed).",
        no_door: "Movement stopped: there's no door in that wall.",
        off_board: "Movement stopped: the path left the board.",
      };
      pushLog([reasons[result.stoppedReason] ?? `Movement stopped (${result.stoppedReason}).`]);
    }
  };

  const handleOpenDoor = async () => {
    if (!pendingDoorId || !heroId) return;
    const result = await runAction(() => openDoor({ gameId, heroId, doorId: pendingDoorId }));
    if (!result) return;
    pushLog([`PLACE TILE: ${result.placementInstruction}`]);
    setPendingDoorId(null);
  };

  const handleSearchTreasure = async () => {
    if (!activeHeroRoomId || !heroId) return;
    const result = await runAction(() =>
      searchTreasure({ gameId, heroId, roomId: activeHeroRoomId, wanderingMonsterDrawn: wanderingDrawn })
    );
    if (!result) return;
    setWanderingDrawn(false);
    if (result.spawnedMonster) pushLog([`PLACE TILE: ${result.spawnedMonster.placementInstruction}`]);
    if (result.monsterAttack) enqueueDefense(result.monsterAttack.heroName, result.monsterAttack.skulls);
  };

  const handleSearchTraps = async () => {
    if (!activeHeroRoomId || !heroId) return;
    const result = await runAction(() => searchTrapsAndSecretDoors({ gameId, heroId, roomId: activeHeroRoomId }));
    if (!result) return;
    for (const t of result.foundTraps) pushLog([`PLACE TILE: ${t.placementInstruction}`]);
    for (const d of result.foundSecretDoors) pushLog([`PLACE TILE: ${d.placementInstruction}`]);
  };

  const handleAttack = async () => {
    if (!attackMonsterId) return;
    const result = await runAction(() => resolveHeroAttack({ gameId, monsterId: attackMonsterId, skulls: attackSkulls }));
    if (!result) return;
    setAttackSkulls(0);
  };

  const handleEndTurn = async () => {
    await runAction(() => endTurn({ gameId }));
    setRolledTurn(null);
  };

  const handleRollTurnType = async () => {
    const result = await runAction(() => rollZargonTurnType({ gameId }));
    if (!result) return;
    setRolledTurn(result);
    setLowestBpHeroId("");
    pushLog([`Zargon rolls: ${result.turnType}`]);
  };

  const handleResolveTurn = async () => {
    if (!rolledTurn) return;
    if (rolledTurn.needsCunningPrompt && !lowestBpHeroId) {
      setErrorMsg("pick the lowest-BP hero first");
      return;
    }
    const result = await runAction(() =>
      resolveZargonTurn({
        gameId,
        turnType: rolledTurn.turnType,
        ...(rolledTurn.needsCunningPrompt ? { lowestBpHeroId } : {}),
      })
    );
    if (!result) return;
    if (result.spawnedMonster) pushLog([`PLACE TILE: ${result.spawnedMonster.placementInstruction}`]);
    for (const mr of result.monsterResults) {
      if (mr.attackedHeroName && mr.skulls !== null) enqueueDefense(mr.attackedHeroName, mr.skulls);
    }
    setRolledTurn(null);
  };

  const handleRecordDefense = async (defense: PendingDefense, shieldsReported: number) => {
    const result = await runAction(() =>
      recordHeroDefense({ gameId, heroId: defense.heroId, skullsFaced: defense.skulls, shieldsReported })
    );
    if (!result) return;
    setPendingDefenses((prev) => prev.filter((d) => d.key !== defense.key));
  };

  return (
    <div className="game-view">
      {game.status === "complete" && narrative && (
        <div
          style={{
            border: "2px solid #e8c34a",
            borderRadius: 6,
            padding: 12,
            marginBottom: 16,
            background: "#2a230f",
            maxWidth: 700,
          }}
        >
          <h2 style={{ margin: 0, color: "#e8c34a" }}>Quest Complete!</h2>
          <p style={{ fontStyle: "italic", color: "#e8dfc8" }}>{narrative.completionText}</p>
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <h2>
          Turn {game.turn} &mdash;{" "}
          {game.phase === "hero"
            ? game.heroes.length === 1
              ? `Hero phase (action ${game.heroPhaseSegment ?? 1} of 2)`
              : "Hero phase"
            : "Zargon's turn"}
        </h2>
        <span className="hint">
          Game <code>{gameId}</code>
        </span>
      </div>

      {narrative && (
        <div style={{ marginBottom: 12 }}>
          <button onClick={() => setNarrativeOpen((v) => !v)}>
            {narrativeOpen ? "Hide" : "Show"} quest story: {narrative.title}
          </button>
          {narrativeOpen && (
            <div style={{ maxWidth: 700 }}>
              <p style={{ fontStyle: "italic", color: "#c9bfa0" }}>{narrative.backstory}</p>
              {narrative.objective && (
                <p>
                  <strong>Objective:</strong> {narrative.objective}
                </p>
              )}
            </div>
          )}
        </div>
      )}

      <BoardView
        gameState={game}
        onConfirmMove={handleConfirmMove}
        onSelectHero={setHeroId}
        onSelectMonster={setAttackMonsterId}
        doors={resolvedDoors}
        stairway={stairway}
        furniture={furniture}
      />

      {errorMsg && <p style={{ color: "#e66" }}>Error: {errorMsg}</p>}

      <div className="actions" style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 12 }}>
        <label>
          Active hero:{" "}
          <select value={heroId} onChange={(e) => setHeroId(e.target.value)}>
            {game.heroes.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
          {activeHeroRoomId && <span className="hint"> in {activeHeroRoomId}</span>}
        </label>

        {game.phase === "hero" && (
          <>
            {pendingDoorId && (
              <div>
                <button onClick={handleOpenDoor} disabled={busy}>
                  Open door {pendingDoorId}
                </button>
              </div>
            )}

            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button onClick={handleSearchTreasure} disabled={busy || !activeHeroRoomId || !!roomAlreadySearchedTreasure}>
                Search treasure
              </button>
              <label>
                <input type="checkbox" checked={wanderingDrawn} onChange={(e) => setWanderingDrawn(e.target.checked)} />{" "}
                wandering monster card drawn
              </label>
              {roomAlreadySearchedTreasure && <span className="hint">(this room has been searched -- once per room)</span>}
            </div>

            <div>
              <button onClick={handleSearchTraps} disabled={busy || !activeHeroRoomId || !!roomAlreadySearchedTraps}>
                Search traps / secret doors
              </button>
              {roomAlreadySearchedTraps && <span className="hint">(this room has been searched -- once per room)</span>}
            </div>

            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <select value={attackMonsterId} onChange={(e) => setAttackMonsterId(e.target.value)}>
                <option value="">Attack target...</option>
                {targetableMonsters.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.type} ({m.id}) &mdash; {m.currentBody} BP
                  </option>
                ))}
              </select>
              <label>
                Skulls: <input type="number" min={0} value={attackSkulls} onChange={(e) => setAttackSkulls(Number(e.target.value))} style={{ width: 48 }} />
              </label>
              <button onClick={handleAttack} disabled={busy || !attackMonsterId}>
                Attack
              </button>
            </div>

            <div>
              <button onClick={handleEndTurn} disabled={busy}>
                {game.heroes.length === 1 && (game.heroPhaseSegment ?? 1) === 1 ? "End action 1 of 2" : "End turn"}
              </button>
            </div>
          </>
        )}

        {game.phase === "zargon" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {!rolledTurn && (
              <button onClick={handleRollTurnType} disabled={busy}>
                Roll Zargon's turn
              </button>
            )}
            {rolledTurn && (
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span>Rolled: {rolledTurn.turnType}</span>
                {rolledTurn.needsCunningPrompt && (
                  <label>
                    Lowest-BP hero:{" "}
                    <select value={lowestBpHeroId} onChange={(e) => setLowestBpHeroId(e.target.value)}>
                      <option value="">choose...</option>
                      {rolledTurn.heroes.map((h) => (
                        <option key={h.id} value={h.id}>
                          {h.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <button onClick={handleResolveTurn} disabled={busy}>
                  Resolve turn
                </button>
              </div>
            )}
          </div>
        )}

        {pendingDefenses.length > 0 && (
          <div className="defenses">
            <h3>Report defenses</h3>
            {pendingDefenses.map((d) => (
              <DefenseForm key={d.key} defense={d} busy={busy} onSubmit={handleRecordDefense} />
            ))}
          </div>
        )}

        <div className="log">
          <h3>Log</h3>
          <ul style={{ maxHeight: 240, overflowY: "auto", fontFamily: "monospace", fontSize: "0.85rem" }}>
            {(game.log ?? []).map((entry, i) => (
              <li key={`g${i}`}>
                [{entry.turn}] {entry.text}
              </li>
            ))}
            {actionLog.map((line, i) => (
              <li key={`a${i}`} style={{ color: line.startsWith("PLACE TILE") ? "#e8b04a" : undefined }}>
                {line}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function DefenseForm({
  defense,
  busy,
  onSubmit,
}: {
  defense: PendingDefense;
  busy: boolean;
  onSubmit: (defense: PendingDefense, shieldsReported: number) => void;
}) {
  const [shields, setShields] = useState(0);
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <span>
        {defense.heroName} faces {defense.skulls} skull(s):
      </span>
      <label>
        Shields rolled: <input type="number" min={0} value={shields} onChange={(e) => setShields(Number(e.target.value))} style={{ width: 48 }} />
      </label>
      <button onClick={() => onSubmit(defense, shields)} disabled={busy}>
        Report
      </button>
    </div>
  );
}
