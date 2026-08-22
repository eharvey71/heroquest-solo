import { useEffect, useMemo, useState } from "react";
import { board as staticBoard, CORRIDOR, type Coord, squareKey } from "../lib/board";
import {
  attemptBreakSpell,
  castSpell,
  endTurn,
  openDoor,
  recordHeroDeath,
  recordHeroDefense,
  resolveHeroAttack,
  resolveMovement,
  resolveTrapAction,
  resolveZargonTurn,
  rollZargonTurnType,
  searchTrapsAndSecretDoors,
  searchTreasure,
  type CombatDieFace,
  undoLastAction,
} from "../lib/functionsClient";
import { livingHeroes, revealedSquareKeys, type MonsterToken } from "../lib/gameState";
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
  const [wanderingDrawn, setWanderingDrawn] = useState(false);
  const [attackMonsterId, setAttackMonsterId] = useState<string>("");
  const [attackSkulls, setAttackSkulls] = useState(0);
  const [spellName, setSpellName] = useState("");
  const [spellSkulls, setSpellSkulls] = useState(0);
  const [spellDefends, setSpellDefends] = useState(true);
  const [spellTargetsMonster, setSpellTargetsMonster] = useState(true);
  const [trapDieFace, setTrapDieFace] = useState<CombatDieFace>("white_shield");
  const [hasToolKit, setHasToolKit] = useState(false);
  const [rolledTurn, setRolledTurn] = useState<{
    turnType: "normal" | "cunning" | "wandering";
    needsCunningPrompt: boolean;
    heroes: { id: string; name: string }[];
  } | null>(null);
  const [lowestBpHeroId, setLowestBpHeroId] = useState<string>("");
  const [pendingDefenses, setPendingDefenses] = useState<PendingDefense[]>([]);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    // A hero who has fallen can't be the active one -- hand the
    // selection to whoever is still standing.
    if (game && (!heroId || !livingHeroes(game.heroes).some((h) => h.id === heroId))) {
      setHeroId(livingHeroes(game.heroes)[0]?.id ?? "");
    }
  }, [game, heroId]);

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

  const handleHeroDeath = async (id: string, name: string) => {
    // Body Points are physical, so this is a report, not a deduction --
    // and it is the one action that can end the quest in a loss.
    if (!window.confirm(`Report ${name} as dead? The figure comes off the board.`)) return;
    await runAction(() => recordHeroDeath({ gameId, heroId: id }));
  };

  const handleBreakSpell = async (id: string, rolledSix: boolean) => {
    await runAction(() => attemptBreakSpell({ gameId, heroId: id, rolledSix }));
  };

  const handleUndo = async () => {
    await runAction(() => undoLastAction({ gameId }));
  };

  const enqueueDefense = (heroName: string, skulls: number) => {
    const hero = game?.heroes.find((h) => h.name === heroName);
    if (!hero) return;
    setPendingDefenses((prev) => [...prev, { key: `${hero.id}-${Date.now()}-${Math.random()}`, heroId: hero.id, heroName, skulls }]);
  };

  // Door/stairway geometry is quest-owned (fetched once); door
  // *state* is game-owned (overrides quest.doors' initial state) --
  // merge them for rendering, same precedence the backend uses (see
  // doors.py). Stairway placement never changes after quest setup.
  //
  // The fallback mirrors engine/doors.py's effective_door_state: a
  // quest-declared "open" means "no lock, no secret", NOT that the door
  // stands open, so with no game-state entry it reads as closed and
  // still needs the Open door button.
  const { doors: questDoors, blockedSquares, stairway, furniture, narrative } = useQuestMap(game?.questId);
  const resolvedDoors = useMemo(
    () =>
      questDoors.map((d) => {
        const live = game?.doors?.[d.id] as DoorState | undefined;
        const fallback: DoorState = d.state === "open" ? "closed" : d.state;
        return { ...d, state: live ?? fallback };
      }),
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

  const heroes = livingHeroes(game.heroes);
  // Chaos spells currently holding heroes. `afraid` doesn't stop a turn,
  // it only costs attack dice, so it shows but never blocks.
  const activeHeroStatuses = game.heroStatus?.[heroId] ?? [];
  const breakableStatus = activeHeroStatuses.find((s) => s.status !== "becalmed");
  const fallenHeroes = game.heroes.filter((h) => h.alive === false);
  // A finished quest -- won or lost -- takes no more actions. Undo still
  // works, so a misreported death is recoverable.
  const playable = game.status !== "complete" && game.status !== "lost";

  const activeHero = heroes.find((h) => h.id === heroId);

  // Hero attacks are WARNED about, never blocked: the app can't see
  // hero weapons (physical/digital boundary), and the rulebook's staff
  // and longsword attack diagonally while dagger and crossbow attack at
  // range -- only the player knows what they're holding. Monsters get no
  // such latitude; the engine requires orthogonal adjacency for them
  // (engine/turn.py).
  const attackReach = (m: MonsterToken): "" | "diagonal" | "not adjacent" => {
    if (!activeHero) return "";
    const dx = Math.abs(m.pos[0] - activeHero.pos[0]);
    const dy = Math.abs(m.pos[1] - activeHero.pos[1]);
    if (dx + dy === 1) return "";
    if (dx === 1 && dy === 1) return "diagonal";
    return "not adjacent";
  };
  const selectedTarget = targetableMonsters.find((m) => m.id === attackMonsterId);
  const selectedReach = selectedTarget ? attackReach(selectedTarget) : "";
  const activeHeroArea = activeHero ? staticBoard.areaOf.get(squareKey(activeHero.pos[0], activeHero.pos[1])) : undefined;
  const activeHeroRoomId = activeHeroArea && activeHeroArea !== CORRIDOR ? activeHeroArea : null;
  const heroSearchedTreasureHere = activeHeroRoomId
    ? (game.searched?.[activeHeroRoomId]?.treasureBy ?? []).includes(heroId)
    : false;
  const roomAlreadySearchedTraps = activeHeroRoomId ? game.searched?.[activeHeroRoomId]?.traps : false;
  const roomAlreadySearchedSecretDoors = activeHeroRoomId ? game.searched?.[activeHeroRoomId]?.secretDoors : false;

  // The 1989 flow: a hero stops AT a door, tells Zargon, and the door
  // opens -- revealing the room without stepping inside (which would
  // otherwise mean walking onto whatever is standing behind it). So any
  // closed door whose threshold the active hero occupies is openable
  // right now; no need to attempt walking through it first.
  const openableDoors = activeHero
    ? resolvedDoors.filter(
        (d) =>
          d.state === "closed" &&
          d.squares.some((sq) => sq[0] === activeHero.pos[0] && sq[1] === activeHero.pos[1])
      )
    : [];

  const handleConfirmMove = async (movingHeroId: string, path: Coord[]) => {
    // Every consequence -- tile instructions, trap springs, why a move
    // stopped short -- is narrated server-side into game.log, which the
    // Firestore subscription renders in order. A second client-side
    // stream used to append its lines at the bottom regardless of when
    // they happened, which read as the log being out of order.
    await runAction(() => resolveMovement({ gameId, heroId: movingHeroId, path }));
  };

  // A trap the party has FOUND is still armed, so movement stops in
  // front of it and the hero chooses. Only found traps are in game
  // state, so this can't leak the quest's hidden ones.
  const adjacentKnownTraps = activeHero
    ? Object.entries(game.trapsFound ?? {})
        .filter(([id, t]) => {
          if ((game.trapsTriggered ?? []).includes(id)) return false;
          const dx = Math.abs(t.pos[0] - activeHero.pos[0]);
          const dy = Math.abs(t.pos[1] - activeHero.pos[1]);
          return dx + dy === 1;
        })
        .map(([id, t]) => ({ id, ...t }))
    : [];

  // Only the Elf and Wizard hold spell cards (rulebook, Dividing The
  // Spells). The cards themselves stay physical -- the app enforces the
  // frame around them: caster, sightline, one cast per quest.
  const isCaster = heroId === "elf" || heroId === "wizard";

  const handleCastSpell = async () => {
    if (!heroId || !spellName.trim()) return;
    const result = await runAction(() =>
      castSpell({
        gameId,
        heroId,
        spellName: spellName.trim(),
        ...(spellTargetsMonster && attackMonsterId ? { targetMonsterId: attackMonsterId } : {}),
        ...(spellTargetsMonster ? { skulls: spellSkulls, monsterDefends: spellDefends } : {}),
      })
    );
    if (!result) return;
    setSpellName("");
    setSpellSkulls(0);
  };

  const handleTrapAction = async (
    trapId: string,
    action: "jump" | "disarm" | "step",
    trapPos: Coord
  ) => {
    if (!heroId || !activeHero) return;
    // Jump lands on the square directly beyond, in the direction of travel.
    const landing: Coord = [
      trapPos[0] + (trapPos[0] - activeHero.pos[0]),
      trapPos[1] + (trapPos[1] - activeHero.pos[1]),
    ];
    const result = await runAction(() =>
      resolveTrapAction({
        gameId,
        heroId,
        trapId,
        action,
        ...(action === "step" ? {} : { dieFace: trapDieFace }),
        ...(action === "jump" ? { landing } : {}),
        ...(action === "disarm" ? { hasToolKit } : {}),
      })
    );
    if (!result) return;
  };

  const handleOpenDoor = async (doorId: string) => {
    if (!heroId) return;
    const result = await runAction(() => openDoor({ gameId, heroId, doorId }));
    if (!result) return;
  };

  const handleSearchTreasure = async () => {
    if (!activeHeroRoomId || !heroId) return;
    const result = await runAction(() =>
      searchTreasure({ gameId, heroId, roomId: activeHeroRoomId, wanderingMonsterDrawn: wanderingDrawn })
    );
    if (!result) return;
    setWanderingDrawn(false);
    if (result.monsterAttack) enqueueDefense(result.monsterAttack.heroName, result.monsterAttack.skulls);
  };

  const handleSearchTraps = async (searchType: "traps" | "secret_doors") => {
    if (!activeHeroRoomId || !heroId) return;
    const result = await runAction(() =>
      searchTrapsAndSecretDoors({ gameId, heroId, roomId: activeHeroRoomId, searchType })
    );
    if (!result) return;
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

      {game.status === "lost" && (
        <div
          style={{
            border: "2px solid #e05c5c",
            borderRadius: 6,
            padding: 12,
            marginBottom: 16,
            background: "#2e1414",
            maxWidth: 700,
          }}
        >
          <h2 style={{ margin: 0, color: "#e05c5c" }}>Quest lost</h2>
          <p style={{ color: "#f0cccc", margin: "6px 0 0" }}>
            Every hero has fallen. Zargon holds the dungeon &mdash; start a new game, or undo if that
            last death was reported by mistake.
          </p>
        </div>
      )}

      {/* The objective is only half the quest -- the rulebook ends it at
          the stairway, so say so until a hero actually gets there. */}
      {game.status !== "complete" && game.objectiveComplete && (
        <div
          style={{
            border: "2px solid #7fb0ff",
            borderRadius: 6,
            padding: 12,
            marginBottom: 16,
            background: "#16233a",
            maxWidth: 700,
          }}
        >
          <h2 style={{ margin: 0, color: "#7fb0ff" }}>Objective complete &mdash; get back to the stairway</h2>
          <p style={{ color: "#cfe0ff", margin: "6px 0 0" }}>
            A quest is only safely finished at the stairway. Any hero reaching it ends the quest.
          </p>
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
        <span style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <button onClick={handleUndo} disabled={busy || !game.undoDepth}>
            {game.undoLabel ? `Undo ${game.undoLabel}` : "Undo"}
          </button>
          <span className="hint">
            Game <code>{gameId}</code>
          </span>
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
        blockedSquares={blockedSquares}
      />

      {errorMsg && <p style={{ color: "#e66" }}>Error: {errorMsg}</p>}

      <div className="actions" style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 12 }}>
        <label>
          Active hero:{" "}
          <select value={heroId} onChange={(e) => setHeroId(e.target.value)}>
            {heroes.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
          {activeHeroRoomId && <span className="hint"> in {activeHeroRoomId}</span>}{" "}
          {activeHero && playable && (
            <button onClick={() => handleHeroDeath(activeHero.id, activeHero.name)} disabled={busy}>
              {activeHero.name} has fallen
            </button>
          )}
        </label>

        {fallenHeroes.length > 0 && (
          <span className="hint">
            Fallen: {fallenHeroes.map((h) => h.name).join(", ")} &mdash; off the board, out of Zargon's reach.
          </span>
        )}

        {activeHeroStatuses.length > 0 && (
          <div style={{ border: "1px solid #7a4b8a", padding: 8, display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ color: "#c79ad6" }}>
              Under a Chaos spell: {activeHeroStatuses.map((s) => `${s.status} (${s.spell})`).join(", ")}
            </span>
            {breakableStatus ? (
              <>
                <span className="hint">
                  Roll one red die for each of this hero&apos;s Mind Points. A 6 breaks the spell.
                </span>
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={() => handleBreakSpell(heroId, true)} disabled={busy}>
                    Rolled a 6 &mdash; break free
                  </button>
                  <button onClick={() => handleBreakSpell(heroId, false)} disabled={busy}>
                    No 6 &mdash; still held
                  </button>
                </div>
              </>
            ) : (
              <span className="hint">The whirlwind passes on its own &mdash; this hero simply misses a turn.</span>
            )}
          </div>
        )}

        {playable && game.phase === "hero" && (
          <>
            {adjacentKnownTraps.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, border: "1px solid #6a5a3a", padding: 8 }}>
                <span className="hint">
                  You know a trap is there. Roll 1 combat die and report the face &mdash; the app never rolls it.
                </span>
                <label>
                  Die:{" "}
                  <select value={trapDieFace} onChange={(e) => setTrapDieFace(e.target.value as CombatDieFace)}>
                    <option value="skull">skull</option>
                    <option value="white_shield">white shield</option>
                    <option value="black_shield">black shield</option>
                  </select>
                </label>
                <label>
                  <input type="checkbox" checked={hasToolKit} onChange={(e) => setHasToolKit(e.target.checked)} /> hero
                  has a tool kit (the Dwarf never needs one)
                </label>
                {adjacentKnownTraps.map((t) => (
                  <div key={t.id} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span>
                      {t.type.replace(/_/g, " ")} at [{t.pos[0]},{t.pos[1]}]
                    </span>
                    <button onClick={() => handleTrapAction(t.id, "jump", t.pos)} disabled={busy}>
                      Jump it
                    </button>
                    <button onClick={() => handleTrapAction(t.id, "disarm", t.pos)} disabled={busy}>
                      Disarm it
                    </button>
                    <button onClick={() => handleTrapAction(t.id, "step", t.pos)} disabled={busy}>
                      Step on it
                    </button>
                  </div>
                ))}
              </div>
            )}

            {openableDoors.length > 0 && (
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                {openableDoors.map((d) => (
                  <button key={d.id} onClick={() => handleOpenDoor(d.id)} disabled={busy}>
                    Open door {d.id}
                  </button>
                ))}
                <span className="hint">(opens from the doorway -- the room is revealed without stepping in)</span>
              </div>
            )}

            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button onClick={handleSearchTreasure} disabled={busy || !activeHeroRoomId || heroSearchedTreasureHere}>
                Search treasure
              </button>
              {activeHeroRoomId && !roomAlreadySearchedTraps && (
                // Derived from what the PARTY has done, not from what the
                // quest hides -- no information leak, just a reminder that
                // greed before caution sets off trapped furniture.
                <span className="hint">this room hasn't been searched for traps yet</span>
              )}
              <label>
                <input type="checkbox" checked={wanderingDrawn} onChange={(e) => setWanderingDrawn(e.target.checked)} />{" "}
                wandering monster card drawn
              </label>
              {heroSearchedTreasureHere && (
                <span className="hint">(this hero already searched this room -- once per hero per room)</span>
              )}
            </div>

            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <button
                onClick={() => handleSearchTraps("traps")}
                disabled={busy || !activeHeroRoomId || !!roomAlreadySearchedTraps}
              >
                Search for traps
              </button>
              {roomAlreadySearchedTraps && <span className="hint">(already searched)</span>}
              <button
                onClick={() => handleSearchTraps("secret_doors")}
                disabled={busy || !activeHeroRoomId || !!roomAlreadySearchedSecretDoors}
              >
                Search for secret doors
              </button>
              {roomAlreadySearchedSecretDoors && <span className="hint">(already searched)</span>}
              <span className="hint">(two separate actions)</span>
            </div>

            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <select value={attackMonsterId} onChange={(e) => setAttackMonsterId(e.target.value)}>
                <option value="">Attack target...</option>
                {targetableMonsters.map((m) => {
                  const reach = attackReach(m);
                  return (
                    <option key={m.id} value={m.id}>
                      {m.type} ({m.id}) &mdash; {m.currentBody} BP
                      {reach && ` \u00b7 ${reach}`}
                    </option>
                  );
                })}
              </select>
              <label>
                Skulls: <input type="number" min={0} value={attackSkulls} onChange={(e) => setAttackSkulls(Number(e.target.value))} style={{ width: 48 }} />
              </label>
              <button onClick={handleAttack} disabled={busy || !attackMonsterId}>
                Attack
              </button>
              {selectedReach && (
                <span style={{ color: "#e6a23b" }}>
                  {selectedReach === "diagonal"
                    ? "diagonal \u2014 staff or longsword only"
                    : "not adjacent \u2014 dagger, crossbow or spell only"}
                </span>
              )}
            </div>

            {isCaster && (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, border: "1px solid #4a5a7a", padding: 8 }}>
                <span className="hint">
                  Cast a spell (instead of attacking). The card stays on the table &mdash; name it, and if it
                  attacks, report the skulls you rolled.
                </span>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <input
                    placeholder="spell name, e.g. Ball of Flame"
                    value={spellName}
                    onChange={(e) => setSpellName(e.target.value)}
                    style={{ minWidth: 200 }}
                  />
                  <label>
                    <input
                      type="checkbox"
                      checked={spellTargetsMonster}
                      onChange={(e) => setSpellTargetsMonster(e.target.checked)}
                    />{" "}
                    at the selected monster
                  </label>
                </div>
                {spellTargetsMonster && (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <label>
                      Skulls:{" "}
                      <input
                        type="number"
                        min={0}
                        value={spellSkulls}
                        onChange={(e) => setSpellSkulls(Number(e.target.value))}
                        style={{ width: 48 }}
                      />
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={spellDefends}
                        onChange={(e) => setSpellDefends(e.target.checked)}
                      />{" "}
                      monster may defend
                    </label>
                  </div>
                )}
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <button
                    onClick={handleCastSpell}
                    disabled={busy || !spellName.trim() || (spellTargetsMonster && !attackMonsterId)}
                  >
                    Cast spell
                  </button>
                  {spellTargetsMonster && !attackMonsterId && (
                    <span className="hint">pick a target above first</span>
                  )}
                  {(game.spellsCast ?? []).length > 0 && (
                    <span className="hint">spent: {(game.spellsCast ?? []).join(", ")}</span>
                  )}
                </div>
              </div>
            )}

            <div>
              <button onClick={handleEndTurn} disabled={busy}>
                {game.heroes.length === 1 && (game.heroPhaseSegment ?? 1) === 1 ? "End action 1 of 2" : "End turn"}
              </button>
            </div>
          </>
        )}

        {playable && game.phase === "zargon" && (
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
            {(game.log ?? []).map((entry, i) => {
              // Tile instructions are the lines the player must act on
              // physically, so they stay visually distinct. Matched on
              // our own generated wording -- see the engines'
              // placement_instruction strings.
              const isTileInstruction = /\b(Place the|Replace the closed door piece)\b/.test(entry.text);
              return (
                <li key={`g${i}`} style={{ color: isTileInstruction ? "#e8b04a" : undefined }}>
                  [{entry.turn}] {entry.text}
                </li>
              );
            })}
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
