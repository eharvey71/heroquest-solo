import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { board as staticBoard, CORRIDOR, type Coord, squareKey } from "../lib/board";
import { crossingKey } from "../lib/boardGeometry";
import { furnitureSquareKeys } from "../lib/furniture";
import { usePathInput } from "../hooks/usePathInput";
import {
  attemptBreakSpell,
  castSpell,
  endTurn,
  generateChronicle,
  generateTurnNarration,
  openDoor,
  recordHeroDeath,
  recordHeroDefense,
  resolveHeroAttack,
  resolveMovement,
  resolveTrapAction,
  resolveTreasureDraw,
  resolveZargonTurn,
  rollZargonTurnType,
  searchTrapsAndSecretDoors,
  searchTreasure,
  type CombatDieFace,
  undoLastAction,
} from "../lib/functionsClient";
import { spellCard, spellsForElements } from "../data/heroSpells";
import { livingHeroes, revealedSquareKeys, type MonsterToken } from "../lib/gameState";
import { useLiveGame } from "../lib/useLiveGame";
import { type DoorState, useQuestMap } from "../lib/useQuestMap";
import { BoardView } from "./BoardView";

interface GameViewProps {
  gameId: string;
}

interface PendingDefense {
  id: string;
  heroId: string;
  heroName: string;
  skulls: number;
  monsterId?: string;
  monsterName?: string;
  pos?: Coord;
}

/** A number field that doesn't fight you: an empty box reads as 0, and
 * focusing selects what's there so typing REPLACES it rather than
 * landing next to a stubborn leading zero. */
function DiceInput({
  value,
  onChange,
  label,
}: {
  value: number;
  onChange: (n: number) => void;
  label: string;
}) {
  return (
    <label>
      {label}{" "}
      <input
        type="number"
        min={0}
        value={value === 0 ? "" : value}
        placeholder="0"
        onFocus={(e) => e.target.select()}
        onChange={(e) => onChange(e.target.value === "" ? 0 : Math.max(0, Number(e.target.value)))}
        style={{ width: 56 }}
      />
    </label>
  );
}

/** A hero takes ONE action per turn (1989 rulebook), so the panel shows
 * a menu of them and expands whichever is picked -- rather than laying
 * every form out at once and letting the player find the right one. */
type ActionKey = "attack" | "search" | "door" | "spell";

const ACTION_LABELS: Record<ActionKey, string> = {
  attack: "Attack",
  search: "Search the room",
  door: "Open a door",
  spell: "Cast a spell",
};

export function GameView({ gameId }: GameViewProps) {
  const { game, loading, error } = useLiveGame(gameId);

  const [heroId, setHeroId] = useState<string>("");
  const [attackMonsterId, setAttackMonsterId] = useState<string>("");
  const [attackSkulls, setAttackSkulls] = useState(0);
  const [spellId, setSpellId] = useState("");
  const [spellTargetHeroId, setSpellTargetHeroId] = useState("");
  const [genieMode, setGenieMode] = useState<"attack" | "door">("attack");
  const [genieDoorId, setGenieDoorId] = useState("");
  const [trapDieFace, setTrapDieFace] = useState<CombatDieFace>("white_shield");
  const [hasToolKit, setHasToolKit] = useState(false);
  const [rolledTurn, setRolledTurn] = useState<{
    turnType: "normal" | "cunning" | "wandering";
    needsCunningPrompt: boolean;
    heroes: { id: string; name: string }[];
  } | null>(null);
  const [lowestBpHeroId, setLowestBpHeroId] = useState<string>("");
  const [openAction, setOpenAction] = useState<ActionKey | null>(null);
  // Dismissal of the "Place on the board" alert (see placements below).
  const [placementsDone, setPlacementsDone] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const logRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    // A hero who has fallen can't be the active one -- hand the
    // selection to whoever is still standing.
    if (game && (!heroId || !livingHeroes(game.heroes).some((h) => h.id === heroId))) {
      setHeroId(livingHeroes(game.heroes)[0]?.id ?? "");
    }
  }, [game, heroId]);

  // Switching hero or phase abandons a half-filled action form: those
  // numbers belonged to the hero who was up a moment ago.
  useEffect(() => {
    setOpenAction(null);
  }, [heroId, game?.phase, game?.heroPhaseSegment]);

  // The newest line is the one you need; without this the log opens
  // scrolled to turn 1 and every entry pushes the interesting end away.
  useEffect(() => {
    const list = logRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [game?.log?.length]);

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
    const result = await runAction(() => undoLastAction({ gameId }));
    if (!result) return;
    // Anything half-entered belonged to the action just rolled back:
    // a traced path, an expanded action form, a rolled-but-unresolved
    // Zargon turn. The defence queue is game state now, so the restore
    // handles that one on its own.
    pathInput.clear();
    setOpenAction(null);
    setRolledTurn(null);
    setLowestBpHeroId("");
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
  const [chronicleOpen, setChronicleOpen] = useState(false);
  const [chronicleRequested, setChronicleRequested] = useState(false);
  const [chronicleError, setChronicleError] = useState<string | null>(null);

  // Written once the quest is actually over -- fired automatically
  // rather than waiting on a button press, since there's no gameplay
  // reason to make the player ask for it. Guarded by chronicleRequested
  // so a re-render (or the chronicle simply not having arrived over
  // Firestore yet) doesn't fire it twice; a genuinely failed request
  // stays failed until the game is reloaded, same as the rest of this
  // app has no automatic retry anywhere else.
  useEffect(() => {
    if (!game) return;
    if (game.status !== "complete" && game.status !== "lost") return;
    if (game.chronicle || chronicleRequested) return;
    setChronicleRequested(true);
    generateChronicle({ gameId }).catch((e) => {
      setChronicleError(e instanceof Error ? e.message : String(e));
    });
  }, [game?.status, game?.chronicle, chronicleRequested, gameId]);

  // Colors each turn's log with a short flavor paragraph as it closes
  // (see generator/narration.py) -- the live, turn-by-turn counterpart
  // to the chronicle's once-per-game summary above. lastSeenTurnRef
  // seeds itself to the CURRENT turn on first render rather than 1, so
  // opening an old game never fires one LLM call per turn of its
  // history at once -- only turns that close from here on get narrated.
  // requestedRef additionally guards against asking twice for the same
  // turn while its request is still in flight.
  const lastSeenTurnRef = useRef<number | null>(null);
  const narrationRequestedRef = useRef<Set<number>>(new Set());
  useEffect(() => {
    if (!game || game.turn === undefined) return;
    const finished = game.status === "complete" || game.status === "lost";

    function request(turn: number) {
      if (game!.narration?.[String(turn)]) return;
      if (narrationRequestedRef.current.has(turn)) return;
      narrationRequestedRef.current.add(turn);
      generateTurnNarration({ gameId, turn }).catch(() => {
        narrationRequestedRef.current.delete(turn);
      });
    }

    if (lastSeenTurnRef.current === null) {
      lastSeenTurnRef.current = game.turn;
      // A game that's already over on first load (e.g. resumed to read
      // its log) has a final turn that will never get a Zargon-turn
      // boundary to close it the normal way -- narrate it now.
      if (finished) request(game.turn);
      return;
    }

    if (game.turn !== lastSeenTurnRef.current) {
      request(lastSeenTurnRef.current);
      lastSeenTurnRef.current = game.turn;
    } else if (finished) {
      request(game.turn);
    }
  }, [game?.turn, game?.status, game?.narration, gameId]);

  // Path tracing lives HERE rather than in BoardView so that "Moving
  // Barbarian -- Confirm" can sit in the rail beside the board. Under
  // the board it was 800px below the thing you had just drawn, and
  // easy to miss entirely. Hooks can't run conditionally, so these are
  // computed before the loading/error returns below.
  const heroTokens = useMemo(() => (game ? livingHeroes(game.heroes) : []), [game]);
  const boardRevealed = useMemo(
    () => (game ? revealedSquareKeys(staticBoard, game.revealed) : new Set<string>()),
    [game]
  );
  const furnitureKeys = useMemo(() => furnitureSquareKeys(furniture), [furniture]);
  // A blocked square and a collapsed ceiling are the same thing to a
  // hero tracing a path: impassable terrain the app can see. A blocked
  // square only counts once it has been SEEN -- the quest's fence is
  // hidden until the fog lifts, and a tracer that refused to draw
  // through an unrevealed one would give it away. The server stops the
  // move there anyway (and calls for the tile).
  const impassableKeys = useMemo(
    () =>
      new Set([
        ...(game?.collapsedSquares ?? []).map((sq) => squareKey(sq[0], sq[1])),
        ...blockedSquares.map((sq) => squareKey(sq[0], sq[1])).filter((key) => boardRevealed.has(key)),
      ]),
    [game?.collapsedSquares, blockedSquares, boardRevealed]
  );
  const doorEdges = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of resolvedDoors) map.set(crossingKey(d.squares[0], d.squares[1]), d.state);
    return map;
  }, [resolvedDoors]);
  const pathInput = usePathInput({
    board: staticBoard,
    heroes: heroTokens,
    monsters: game?.monsters ?? [],
    revealed: boardRevealed,
    furniture: furnitureKeys,
    collapsed: impassableKeys,
    doorEdges,
  });

  if (loading) return <p>Loading game...</p>;
  if (error) return <p style={{ color: "#e66" }}>Error: {error}</p>;
  if (!game) return null;

  // Zargon's unanswered attacks, straight off the live document: held
  // in React state they outlived an undo of the very turn that raised
  // them, and a refresh lost them altogether.
  const pendingDefenses: PendingDefense[] = game.pendingDefenses ?? [];
  // Whichever monsters are still waiting on a shield report -- the
  // board highlights each one, and the highlight drops the instant its
  // entry leaves the queue (defence reported, undone, or the turn
  // that raised it undone).
  const attackingMonsterIds = new Set(pendingDefenses.map((d) => d.monsterId).filter((id): id is string => !!id));
  // A treasure search whose physical card hasn't been reported yet --
  // the app can't rule on anything else until it hears whether the
  // wandering monster came up, so this gates actions exactly like an
  // unanswered defence roll (and the server enforces the same).
  const pendingTreasureDraw = game.pendingTreasureDraw ?? null;
  const waitingOnReport = pendingDefenses.length > 0 || !!pendingTreasureDraw;
  // Tiles and minis the player still has to put on the physical board.
  const placements: string[] = game.placementInstructions ?? [];
  // Keyed on the instruction text so a NEW reveal (different content)
  // shows again on its own; placementsDone is declared up with the
  // other hooks -- a useState below the early returns crashed React
  // (hooks must run unconditionally, every render).
  const placementsKey = placements.join("|");
  const showPlacements = placements.length > 0 && placementsDone !== placementsKey;

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
  // Only the cards this hero is actually holding: the elements were
  // chosen when the game was created (game state's spellbooks).
  const heldSpells = spellsForElements(game.spellbooks?.[heroId]);
  const chosenCard = spellId ? spellCard(spellId) : undefined;
  // "Open any door ON THE BOARD": the doors on the board are the ones
  // that have been placed. Listing every door in the quest would hand
  // over the map -- same visibility rule the renderer uses.
  const genieDoors = resolvedDoors
    .filter((d) => d.state === "closed" && d.squares.some((sq) => revealedKeys.has(squareKey(sq[0], sq[1]))))
    .map((d) => {
      const seenFrom = d.squares.find((sq) => revealedKeys.has(squareKey(sq[0], sq[1]))) ?? d.squares[0];
      const area = staticBoard.areaOf.get(squareKey(seenFrom[0], seenFrom[1]));
      return { ...d, label: `${area === CORRIDOR ? "corridor" : area} at [${seenFrom[0]},${seenFrom[1]}]` };
    });
  const spellWantsMonster =
    chosenCard?.target === "monster" || (chosenCard?.target === "choice" && genieMode === "attack");

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

  const movingHero = heroes.find((h) => h.id === pathInput.selectedHeroId);
  const tracedSteps = Math.max(pathInput.path.length - 1, 0);

  const handleConfirmTracedMove = async () => {
    if (!movingHero || !pathInput.canConfirm) return;
    const path = pathInput.path;
    pathInput.clear();
    await handleConfirmMove(movingHero.id, path);
  };

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

  // A SPRUNG pit next to the hero: crossing the open hole is never
  // free (rulebook p.19-20) -- jump it or climb in. Movement already
  // stops at its edge server-side; this panel resolves the choice.
  const adjacentOpenPits = activeHero
    ? Object.entries(game.trapsFound ?? {})
        .filter(([id, t]) => {
          if (t.type !== "pit" || !(game.trapsTriggered ?? []).includes(id)) return false;
          const dx = Math.abs(t.pos[0] - activeHero.pos[0]);
          const dy = Math.abs(t.pos[1] - activeHero.pos[1]);
          return dx + dy === 1;
        })
        .map(([id, t]) => ({ id, ...t }))
    : [];


  const handleCastSpell = async () => {
    if (!heroId || !spellId) return;
    const card = spellCard(spellId);
    const wantsMonster = card?.target === "monster" || (card?.target === "choice" && genieMode === "attack");
    const result = await runAction(() =>
      castSpell({
        gameId,
        heroId,
        spellId,
        ...(wantsMonster && attackMonsterId ? { targetMonsterId: attackMonsterId } : {}),
        ...(card?.target === "hero" ? { targetHeroId: spellTargetHeroId || heroId } : {}),
        ...(card?.target === "choice" ? { genieMode, ...(genieMode === "door" ? { doorId: genieDoorId } : {}) } : {}),
      })
    );
    if (!result) return;
    setSpellId("");
    setOpenAction(null);
  };

  const handleTrapAction = async (
    trapId: string,
    action: "jump" | "disarm" | "step",
    trapPos: Coord,
    // Spear rows report the die with the button itself (one click);
    // everything else reads the dropdown.
    dieFaceOverride?: CombatDieFace
  ) => {
    if (!heroId || !activeHero) return;
    // Jump lands on the square directly beyond, in the direction of travel.
    const landing: Coord = [
      trapPos[0] + (trapPos[0] - activeHero.pos[0]),
      trapPos[1] + (trapPos[1] - activeHero.pos[1]),
    ];
    // dieFace ALWAYS goes along: a step onto a spear is a reflex roll
    // the server refuses to resolve without it, and the extra field is
    // ignored where it isn't needed. Omitting it for "step" made the
    // Step button error out on every spear no matter what die the
    // dropdown showed.
    const result = await runAction(() =>
      resolveTrapAction({
        gameId,
        heroId,
        trapId,
        action,
        dieFace: dieFaceOverride ?? trapDieFace,
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
    // No wanderingMonsterDrawn flag: the player can't know what the
    // card is until AFTER this call rules the search legal and
    // un-trapped. The server leaves pendingTreasureDraw on the game and
    // the "Draw a treasure card" prompt takes it from there.
    await runAction(() => searchTreasure({ gameId, heroId, roomId: activeHeroRoomId }));
  };

  const handleResolveTreasureDraw = async (wanderingMonsterDrawn: boolean) => {
    await runAction(() => resolveTreasureDraw({ gameId, wanderingMonsterDrawn }));
    // A drawn wandering monster attacks at once; the server queues that
    // defence prompt in the game document, so it arrives with the live
    // state like any other.
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
    // The prompts arrive through the live game document, which
    // resolve_zargon_turn has already written -- nothing to mirror here.
    setRolledTurn(null);
  };

  const handleRecordDefense = async (defense: PendingDefense, shieldsReported: number) => {
    await runAction(() =>
      recordHeroDefense({
        gameId,
        heroId: defense.heroId,
        skullsFaced: defense.skulls,
        shieldsReported,
        defenseId: defense.id,
      })
    );
  };

  return (
    <div className="game-view">
      {game.status === "complete" && narrative && (
        <div className="banner">
          <h2>Quest Complete!</h2>
          <p style={{ fontStyle: "italic", color: "#e8dfc8" }}>{narrative.completionText}</p>
        </div>
      )}

      {game.status === "lost" && (
        <div className="banner banner-lost">
          <h2>Quest lost</h2>
          <p style={{ color: "#f0cccc", margin: "6px 0 0" }}>
            Every hero has fallen. Zargon holds the dungeon &mdash; start a new game, or undo if that last
            death was reported by mistake.
          </p>
        </div>
      )}

      {/* The objective is only half the quest -- the rulebook ends it at
          the stairway, so say so until a hero actually gets there. */}
      {game.status !== "complete" && game.objectiveComplete && (
        <div className="banner banner-objective">
          <h2>Objective complete &mdash; get back to the stairway</h2>
          <p style={{ color: "#cfe0ff", margin: "6px 0 0" }}>
            A quest is only safely finished at the stairway. Any hero reaching it ends the quest.
          </p>
        </div>
      )}

      <div className="app-header">
        <h2 style={{ margin: 0 }}>
          Turn {game.turn} &mdash;{" "}
          {game.phase === "hero"
            ? game.heroes.length === 1
              ? `Hero phase (action ${game.heroPhaseSegment ?? 1} of 2)`
              : "Hero phase"
            : "Zargon's turn"}
        </h2>
        <span style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          {narrative && (
            <button className="quiet" onClick={() => setNarrativeOpen(true)}>
              Story
            </button>
          )}
          {!playable && game.chronicle && (
            <button className="quiet" onClick={() => setChronicleOpen(true)}>
              Chronicle
            </button>
          )}
          {!playable && !game.chronicle && !chronicleError && (
            <span className="hint">Writing the chronicle&hellip;</span>
          )}
          {!playable && !game.chronicle && chronicleError && (
            <span className="hint" style={{ color: "#e6a23b" }}>
              Chronicle failed to generate
            </span>
          )}
          <button onClick={handleUndo} disabled={busy || !game.undoDepth}>
            {game.undoLabel ? `Undo ${game.undoLabel}` : "Undo"}
          </button>
          <span className="hint">
            <code>{gameId}</code>
          </span>
        </span>
      </div>

      {narrative && narrativeOpen && (
        // Click anywhere outside to put it away -- it is read-aloud text,
        // not a form.
        <div className="story-overlay" onClick={() => setNarrativeOpen(false)}>
          <div className="story-card" onClick={(e) => e.stopPropagation()}>
            <h3>{narrative.title}</h3>
            <p style={{ fontStyle: "italic", color: "#c9bfa0" }}>{narrative.backstory}</p>
            {narrative.objective && (
              <p>
                <strong>Objective:</strong> {narrative.objective}
              </p>
            )}
            <button onClick={() => setNarrativeOpen(false)}>Close</button>
          </div>
        </div>
      )}

      {game.chronicle && chronicleOpen && (
        <div className="story-overlay" onClick={() => setChronicleOpen(false)}>
          <div className="story-card" onClick={(e) => e.stopPropagation()}>
            <h3>Chronicle</h3>
            <p style={{ whiteSpace: "pre-wrap" }}>{game.chronicle}</p>
            <button onClick={() => setChronicleOpen(false)}>Close</button>
          </div>
        </div>
      )}

      {errorMsg && <p style={{ color: "#e66" }}>Error: {errorMsg}</p>}

      <div className="game-layout">
        <div className="board-pane">
          <BoardView
            gameState={game}
            pathInput={pathInput}
            onSelectHero={setHeroId}
            onSelectMonster={setAttackMonsterId}
            doors={resolvedDoors}
            stairway={stairway}
            furniture={furniture}
            // A square sealed by a sprung falling block is physically a
            // blocked square from then on -- drawn the same way, so the
            // player sees WHY the tracer refuses it.
            blockedSquares={[...blockedSquares, ...(game.collapsedSquares ?? [])]}
            activeHeroId={heroId}
            activeMonsterId={attackMonsterId}
            attackingMonsterIds={attackingMonsterIds}
          />
        </div>

        <div className="rail">
          {/* Anything the app is WAITING on comes first, before the
              things you might choose to do. */}
          {showPlacements && (
            <div className="alert alert-place">
              <p className="alert-title">Place on the board</p>
              <ul className="log-list">
                {placements.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
              <button className="quiet" onClick={() => setPlacementsDone(placementsKey)}>
                Done
              </button>
            </div>
          )}

          {pendingDefenses.length > 0 && (
            <div className="alert">
              <p className="alert-title">Report defence rolls</p>
              <div className="panel-stack">
                {pendingDefenses.map((d) => (
                  <DefenseForm key={d.id} defense={d} busy={busy} onSubmit={handleRecordDefense} />
                ))}
              </div>
            </div>
          )}

          {pendingTreasureDraw && (
            <div className="alert">
              <p className="alert-title">Draw a treasure card</p>
              <div className="panel-stack">
                <span>
                  Draw ONE card from the treasure deck for{" "}
                  {game.heroes.find((h) => h.id === pendingTreasureDraw.heroId)?.name ?? "the searcher"}. Was it the
                  wandering monster?
                </span>
                <div className="panel-row">
                  <button className="primary" onClick={() => handleResolveTreasureDraw(true)} disabled={busy}>
                    Wandering monster!
                  </button>
                  <button onClick={() => handleResolveTreasureDraw(false)} disabled={busy}>
                    No &mdash; an ordinary card
                  </button>
                </div>
                <span className="hint">
                  Any other card &mdash; gold, a potion, a hazard &mdash; is yours to resolve at the table; the app
                  never needs to see it.
                </span>
              </div>
            </div>
          )}

          {activeHeroStatuses.length > 0 && (
            <div className="alert alert-spell">
              <p className="alert-title">
                {activeHero?.name ?? "This hero"} is under a Chaos spell
              </p>
              <div className="panel-stack">
                <span style={{ color: "#c79ad6" }}>
                  {activeHeroStatuses.map((s) => `${s.status} (${s.spell})`).join(", ")}
                </span>
                {breakableStatus ? (
                  <>
                    <span className="hint">
                      Roll one red die for each of this hero&apos;s Mind Points. A 6 breaks the spell.
                    </span>
                    <div className="panel-row">
                      <button className="primary" onClick={() => handleBreakSpell(heroId, true)} disabled={busy}>
                        Rolled a 6
                      </button>
                      <button onClick={() => handleBreakSpell(heroId, false)} disabled={busy}>
                        No 6 &mdash; still held
                      </button>
                    </div>
                  </>
                ) : (
                  <span className="hint">
                    The whirlwind passes on its own &mdash; this hero simply misses a turn.
                  </span>
                )}
              </div>
            </div>
          )}

          {playable && game.phase === "hero" && !waitingOnReport && adjacentKnownTraps.length > 0 && (
            <div className="alert">
              <p className="alert-title">A known trap is beside this hero</p>
              <div className="panel-stack">
                {adjacentKnownTraps.map((t) =>
                  t.type === "spear" ? (
                    // A spear is a reflex, not a choice: the hero
                    // stepped onto it and owes exactly one die. One
                    // click reports it -- no dropdown, no separate
                    // confirm.
                    <div key={t.id} className="panel-stack">
                      <span>
                        Spear trap at [{t.pos[0]},{t.pos[1]}] &mdash; roll 1 combat die and press the face you rolled.
                        A skull costs 1 Body Point and ends the turn; either shield dodges it and the spear is gone.
                      </span>
                      <div className="panel-row">
                        <button className="primary" onClick={() => handleTrapAction(t.id, "step", t.pos, "skull")} disabled={busy}>
                          Skull
                        </button>
                        <button onClick={() => handleTrapAction(t.id, "step", t.pos, "white_shield")} disabled={busy}>
                          White shield
                        </button>
                        <button onClick={() => handleTrapAction(t.id, "step", t.pos, "black_shield")} disabled={busy}>
                          Black shield
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div key={t.id} className="panel-stack">
                      <span>
                        {t.type === "falling_block" ? "Falling block" : "Pit"} trap at [{t.pos[0]},{t.pos[1]}] &mdash;
                        still armed. Jump and Disarm need a die roll (set it below first); stepping on just springs
                        it, no roll. Or simply walk another way &mdash; it only matters if you cross its square.
                      </span>
                      <div className="panel-row">
                        <label>
                          Die rolled:{" "}
                          <select value={trapDieFace} onChange={(e) => setTrapDieFace(e.target.value as CombatDieFace)}>
                            <option value="skull">skull</option>
                            <option value="white_shield">white shield</option>
                            <option value="black_shield">black shield</option>
                          </select>
                        </label>
                        <label>
                          <input type="checkbox" checked={hasToolKit} onChange={(e) => setHasToolKit(e.target.checked)} />{" "}
                          tool kit
                        </label>
                      </div>
                      <div className="panel-row">
                        <button onClick={() => handleTrapAction(t.id, "jump", t.pos)} disabled={busy}>
                          Jump (skull springs it)
                        </button>
                        <button onClick={() => handleTrapAction(t.id, "disarm", t.pos)} disabled={busy}>
                          Disarm
                        </button>
                        <button onClick={() => handleTrapAction(t.id, "step", t.pos)} disabled={busy}>
                          Step on it (springs it)
                        </button>
                      </div>
                    </div>
                  )
                )}
                <span className="hint">
                  A cleared jump leaves the trap ARMED &mdash; this panel stays while the hero stands next to it.
                </span>
              </div>
            </div>
          )}

          {playable && game.phase === "hero" && !waitingOnReport && adjacentOpenPits.length > 0 && (
            <div className="alert">
              <p className="alert-title">An open pit is beside this hero</p>
              <div className="panel-stack">
                {adjacentOpenPits.map((t) => (
                  <div key={t.id} className="panel-stack">
                    <span>
                      Open pit at [{t.pos[0]},{t.pos[1]}] &mdash; crossing it means jumping (2 squares of movement,
                      roll 1 combat die: anything but a skull clears it) or climbing in for 1 Body Point.
                    </span>
                    <div className="panel-row">
                      <button className="primary" onClick={() => handleTrapAction(t.id, "jump", t.pos, "white_shield")} disabled={busy}>
                        Jumped &mdash; no skull
                      </button>
                      <button onClick={() => handleTrapAction(t.id, "jump", t.pos, "skull")} disabled={busy}>
                        Skull &mdash; fell in
                      </button>
                      <button onClick={() => handleTrapAction(t.id, "step", t.pos)} disabled={busy}>
                        Climb in
                      </button>
                    </div>
                  </div>
                ))}
                <span className="hint">
                  In the pit: attack and defend with one die fewer; climbing out is next turn&apos;s movement.
                  Monsters clear open pits automatically.
                </span>
              </div>
            </div>
          )}

          <div className="panel">
            <p className="panel-title">Active hero</p>
            <div className="panel-stack">
              <div className="panel-row" style={{ justifyContent: "space-between" }}>
                <span className="panel-row">
                  <select className="active-hero-select" value={heroId} onChange={(e) => setHeroId(e.target.value)}>
                    {heroes.map((h) => (
                      <option key={h.id} value={h.id}>
                        {h.name}
                      </option>
                    ))}
                  </select>
                  <span className="hint">{activeHeroRoomId ? `in ${activeHeroRoomId}` : "in a corridor"}</span>
                </span>
                {activeHero && playable && (
                  <button
                    className="quiet"
                    onClick={() => handleHeroDeath(activeHero.id, activeHero.name)}
                    disabled={busy}
                  >
                    Has fallen
                  </button>
                )}
              </div>
              {fallenHeroes.length > 0 && (
                <span className="hint">Fallen: {fallenHeroes.map((h) => h.name).join(", ")}</span>
              )}
            </div>
          </div>

          {playable && game.phase === "hero" && movingHero && tracedSteps > 0 && (
            <div className="panel">
              <p className="panel-title">Move</p>
              <div className="panel-stack">
                <span>
                  {movingHero.name} &mdash; {tracedSteps} step{tracedSteps === 1 ? "" : "s"} traced
                </span>
                {pathInput.blockedHint && <span style={{ color: "#e6a23b" }}>{pathInput.blockedHint}</span>}
                {!pathInput.blockedHint && pathInput.endSquareOccupied && (
                  <span style={{ color: "#e6a23b" }}>can&apos;t end the move on an occupied square</span>
                )}
                {waitingOnReport && (
                  <span className="hint">Answer the prompt(s) above before confirming a move.</span>
                )}
                <div className="panel-row">
                  <button
                    className="primary"
                    onClick={handleConfirmTracedMove}
                    disabled={busy || !pathInput.canConfirm || waitingOnReport}
                  >
                    Confirm move
                  </button>
                  <button className="quiet" onClick={pathInput.clear} disabled={busy}>
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

          {playable && game.phase === "hero" && (
            <div className="panel">
              <p className="panel-title">
                {openAction ? ACTION_LABELS[openAction] : "Action — one per turn"}
              </p>

              {waitingOnReport ? (
                // A hit from Zargon's last turn is unresolved, or a
                // treasure card is drawn but unreported. Physically
                // you'd resolve either before doing anything else --
                // so no other action (or ending the turn) is available
                // until every prompt above is answered.
                <p className="hint">
                  {pendingDefenses.length > 0
                    ? "Report the defence roll(s) above before anyone can act."
                    : "Report the treasure card above before anyone can act."}
                </p>
              ) : (
                <>
              {openAction === null && (
                <div className="panel-stack">
                  <div className="action-grid">
                    <button onClick={() => setOpenAction("attack")} disabled={busy || targetableMonsters.length === 0}>
                      Attack
                    </button>
                    <button onClick={() => setOpenAction("search")} disabled={busy || !activeHeroRoomId}>
                      Search
                    </button>
                    {openableDoors.length > 0 && (
                      <button onClick={() => setOpenAction("door")} disabled={busy}>
                        Open door
                      </button>
                    )}
                    {heldSpells.length > 0 && (
                      <button onClick={() => setOpenAction("spell")} disabled={busy}>
                        Cast spell
                      </button>
                    )}
                  </div>
                  <span className="hint">
                    Trace a path on the board to move. Attacking, searching, opening a door or casting is
                    the hero&apos;s one action.
                  </span>
                  <div>
                    <button className="primary" onClick={handleEndTurn} disabled={busy}>
                      {game.heroes.length === 1 && (game.heroPhaseSegment ?? 1) === 1
                        ? "End action 1 of 2"
                        : "End turn"}
                    </button>
                  </div>
                </div>
              )}

              {openAction === "attack" && (
                <div className="panel-stack">
                  <div className="panel-row">
                    <select value={attackMonsterId} onChange={(e) => setAttackMonsterId(e.target.value)}>
                      <option value="">Target...</option>
                      {targetableMonsters.map((m) => {
                        const reach = attackReach(m);
                        return (
                          <option key={m.id} value={m.id}>
                            {m.type} ({m.id}) &mdash; {m.currentBody} BP
                            {reach && ` · ${reach}`}
                          </option>
                        );
                      })}
                    </select>
                    <DiceInput label="Skulls:" value={attackSkulls} onChange={setAttackSkulls} />
                  </div>
                  {selectedReach && (
                    <span style={{ color: "#e6a23b" }}>
                      {selectedReach === "diagonal"
                        ? "diagonal — staff or longsword only"
                        : "not adjacent — dagger, crossbow or spell only"}
                    </span>
                  )}
                  <div className="panel-row">
                    <button className="primary" onClick={handleAttack} disabled={busy || !attackMonsterId}>
                      Roll it
                    </button>
                    <button className="quiet" onClick={() => setOpenAction(null)} disabled={busy}>
                      Back
                    </button>
                  </div>
                </div>
              )}

              {openAction === "search" && (
                <div className="panel-stack">
                  <div className="panel-row">
                    <button
                      onClick={handleSearchTreasure}
                      disabled={busy || !activeHeroRoomId || heroSearchedTreasureHere}
                    >
                      Treasure
                    </button>
                    <button
                      onClick={() => handleSearchTraps("traps")}
                      disabled={busy || !activeHeroRoomId || !!roomAlreadySearchedTraps}
                    >
                      Traps
                    </button>
                    <button
                      onClick={() => handleSearchTraps("secret_doors")}
                      disabled={busy || !activeHeroRoomId || !!roomAlreadySearchedSecretDoors}
                    >
                      Secret doors
                    </button>
                  </div>
                  <span className="hint">
                    {heroSearchedTreasureHere
                      ? "This hero already searched here for treasure -- once per hero per room."
                      : roomAlreadySearchedTraps
                        ? // "Searched", not "found" -- the flag only means the
                          // search happened; the log says what turned up.
                          "This room has been searched for traps -- treasure is safe to search now."
                        : "Searching for treasure before traps sets off any trapped chest in the room."}
                  </span>
                  <span className="hint">
                    Treasure: press first, draw after &mdash; the app will ask what the card was.
                  </span>
                  <div>
                    <button className="quiet" onClick={() => setOpenAction(null)} disabled={busy}>
                      Back
                    </button>
                  </div>
                </div>
              )}

              {openAction === "door" && (
                <div className="panel-stack">
                  <div className="panel-row">
                    {openableDoors.map((d) => (
                      <button key={d.id} className="primary" onClick={() => handleOpenDoor(d.id)} disabled={busy}>
                        Open {d.id}
                      </button>
                    ))}
                  </div>
                  <span className="hint">
                    Opens from the doorway &mdash; the room is revealed without stepping in.
                  </span>
                  <div>
                    <button className="quiet" onClick={() => setOpenAction(null)} disabled={busy}>
                      Back
                    </button>
                  </div>
                </div>
              )}

              {openAction === "spell" && (
                <div className="panel-stack">
                  {heldSpells.length === 0 ? (
                    <span className="hint">
                      This hero holds no spell cards. The Wizard and Elf pick their elements when the game
                      is created.
                    </span>
                  ) : (
                    <>
                      <select value={spellId} onChange={(e) => setSpellId(e.target.value)}>
                        <option value="">Which card?</option>
                        {heldSpells.map((card) => {
                          const spent = (game.spellsCast ?? []).includes(card.id);
                          return (
                            <option key={card.id} value={card.id} disabled={spent}>
                              {card.element} &middot; {card.name}
                              {spent ? " -- cast" : ""}
                            </option>
                          );
                        })}
                      </select>
                      {chosenCard && <span className="hint">{chosenCard.summary}</span>}

                      {chosenCard?.target === "hero" && (
                        <label>
                          On:{" "}
                          <select
                            value={spellTargetHeroId || heroId}
                            onChange={(e) => setSpellTargetHeroId(e.target.value)}
                          >
                            {heroes.map((h) => (
                              <option key={h.id} value={h.id}>
                                {h.name}
                                {h.id === heroId ? " (self)" : ""}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}

                      {chosenCard?.target === "choice" && (
                        <div className="panel-row">
                          <label>
                            <input
                              type="radio"
                              checked={genieMode === "attack"}
                              onChange={() => setGenieMode("attack")}
                            />{" "}
                            attack
                          </label>
                          <label>
                            <input
                              type="radio"
                              checked={genieMode === "door"}
                              onChange={() => setGenieMode("door")}
                            />{" "}
                            open a door
                          </label>
                        </div>
                      )}

                      {chosenCard?.target === "choice" && genieMode === "door" && genieDoors.length === 0 && (
                        <span style={{ color: "#e6a23b" }}>
                          No closed door is on the board yet &mdash; the Genie can only open one the party
                          has found.
                        </span>
                      )}

                      {chosenCard?.target === "choice" && genieMode === "door" && genieDoors.length > 0 && (
                        <label>
                          Door:{" "}
                          <select value={genieDoorId} onChange={(e) => setGenieDoorId(e.target.value)}>
                            <option value="">Which one?</option>
                            {genieDoors.map((d) => (
                              <option key={d.id} value={d.id}>
                                {d.label}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}

                      {spellWantsMonster && (
                        <label>
                          Target:{" "}
                          <select value={attackMonsterId} onChange={(e) => setAttackMonsterId(e.target.value)}>
                            <option value="">Which monster?</option>
                            {targetableMonsters.map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.type} ({m.id}) &mdash; {m.currentBody} BP
                              </option>
                            ))}
                          </select>
                        </label>
                      )}

                      <div className="panel-row">
                        <button
                          className="primary"
                          onClick={handleCastSpell}
                          disabled={
                            busy ||
                            !spellId ||
                            (spellWantsMonster && !attackMonsterId) ||
                            (chosenCard?.target === "choice" && genieMode === "door" && !genieDoorId)
                          }
                        >
                          Cast
                        </button>
                        <button className="quiet" onClick={() => setOpenAction(null)} disabled={busy}>
                          Back
                        </button>
                      </div>
                      <span className="hint">
                        The app applies what it can see and tells you the rest &mdash; Body Points and your
                        own dice stay on the table.
                      </span>
                    </>
                  )}
                </div>
              )}
                </>
              )}
            </div>
          )}

          {playable && game.phase === "zargon" && (
            <div className="panel">
              <p className="panel-title">Zargon&apos;s turn</p>
              <div className="panel-stack">
                {!rolledTurn && (
                  <div>
                    <button className="primary" onClick={handleRollTurnType} disabled={busy}>
                      Roll Zargon&apos;s turn
                    </button>
                  </div>
                )}
                {rolledTurn && (
                  <>
                    <span>
                      Rolled: <strong>{rolledTurn.turnType}</strong>
                    </span>
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
                    <div>
                      <button className="primary" onClick={handleResolveTurn} disabled={busy}>
                        Resolve turn
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}

          <div className="panel">
            <p className="panel-title">Log</p>
            <ul className="log-list" ref={logRef}>
              {(() => {
                const entries = game.log ?? [];
                const narration = game.narration ?? {};
                const nodes: ReactNode[] = [];
                const narrationLine = (turn: number) =>
                  narration[String(turn)] && (
                    <li key={`narration-${turn}`} className="log-narration">
                      {narration[String(turn)]}
                    </li>
                  );
                entries.forEach((entry, i) => {
                  const prev = entries[i - 1];
                  // A turn boundary: the previous turn's flavor line
                  // belongs after its last log entry, not before this
                  // turn's own first one.
                  if (prev && prev.turn !== entry.turn) nodes.push(narrationLine(prev.turn));
                  // Tile instructions are the lines the player must act
                  // on physically, so they stay visually distinct.
                  // Matched on our own generated wording -- see the
                  // engines' placement_instruction strings.
                  const isTileInstruction = /\b(Place the|Replace the closed door piece)\b/.test(entry.text);
                  nodes.push(
                    <li key={`g${i}`} className={isTileInstruction ? "log-tile" : undefined}>
                      [{entry.turn}] {entry.text}
                    </li>
                  );
                });
                const last = entries[entries.length - 1];
                if (last) nodes.push(narrationLine(last.turn));
                return nodes;
              })()}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

// The owner's box has 6 physical combat dice -- no defend roll can ever
// come up with more shields than that, so the full range of possible
// answers fits in one row of buttons. One click reports the result;
// no typing a number and then pressing a separate Report button.
const SHIELD_COUNTS = [0, 1, 2, 3, 4, 5, 6];

function DefenseForm({
  defense,
  busy,
  onSubmit,
}: {
  defense: PendingDefense;
  busy: boolean;
  onSubmit: (defense: PendingDefense, shieldsReported: number) => void;
}) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <span>
        {defense.heroName} faces {defense.skulls} skull(s)
        {defense.monsterName ? ` from the ${defense.monsterName.replace(/_/g, " ")}` : ""}
        {defense.pos ? ` at (${defense.pos[0]}, ${defense.pos[1]})` : ""}:
      </span>
      <span className="hint">Shields rolled:</span>
      <div className="shield-count-row">
        {SHIELD_COUNTS.map((n) => (
          <button key={n} onClick={() => onSubmit(defense, n)} disabled={busy}>
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}
