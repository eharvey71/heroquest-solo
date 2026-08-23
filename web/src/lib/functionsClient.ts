/**
 * Typed httpsCallable wrappers for every live-game Cloud Function in
 * functions/main.py. Field names here are camelCase to match each
 * endpoint's actual req.data / return shape exactly (verified against
 * main.py, not guessed) -- Python's snake_case never crosses this
 * boundary.
 */

import { type HttpsCallableOptions, httpsCallable } from "firebase/functions";
import type { Coord } from "./board";
import { functions } from "./firebase";

function call<Req, Res>(name: string, options?: HttpsCallableOptions) {
  const callable = httpsCallable<Req, Res>(functions, name, options);
  return async (data: Req): Promise<Res> => {
    const result = await callable(data);
    return result.data;
  };
}

// ---- generateQuest ----

export interface GenerateQuestRequest {
  heroCount: 1 | 2 | 3 | 4;
  difficulty?: "standard" | "hard";
  size?: "short" | "full";
  theme?: string;
}
export interface GenerateQuestResponse {
  questId: string;
}
// generate_quest's backend timeout_sec=480 (up to 3 LLM round trips at
// high effort, ~100s each) -- the JS SDK's own default callable
// timeout is only 70s, which cuts this off long before the backend
// would ever time out.
export const generateQuest = call<GenerateQuestRequest, GenerateQuestResponse>("generate_quest", {
  timeout: 480_000,
});

// ---- generateChronicle ----

export interface GenerateChronicleRequest {
  gameId: string;
}
export interface GenerateChronicleResponse {
  chronicle: string;
}
// Backend timeout_sec=120 -- comfortably past the JS SDK's 70s default,
// same reasoning as generateQuest above (one LLM round trip, no retry
// loop, so it needs far less headroom than quest generation does).
export const generateChronicle = call<GenerateChronicleRequest, GenerateChronicleResponse>("generate_chronicle", {
  timeout: 120_000,
});

// ---- createGame ----

export interface CreateGameRequest {
  questId: string;
  heroes: { id: string; name?: string }[];
  /** Which spell elements each caster took at the table: the Wizard
   * three, the Elf one of what's left. */
  spellbooks?: Record<string, string[]>;
}
export interface CreateGameResponse {
  gameId: string;
}
export const createGame = call<CreateGameRequest, CreateGameResponse>("create_game");

// ---- resolveMovement ----

export interface ResolveMovementRequest {
  gameId: string;
  heroId: string;
  path: Coord[];
}
export interface TriggeredTrap {
  trapId: string;
  type: string;
  pos: Coord;
  placementInstruction: string;
}
export interface ResolveMovementResponse {
  finalPos: Coord;
  pathTaken: Coord[];
  stoppedReason: string | null;
  stoppedAtDoorId: string | null;
  newlyRevealedRooms: string[];
  triggeredTraps: TriggeredTrap[];
  log: string[];
}
export const resolveMovement = call<ResolveMovementRequest, ResolveMovementResponse>("resolve_movement");

// ---- openDoor ----

export interface OpenDoorRequest {
  gameId: string;
  heroId: string;
  doorId: string;
}
export interface OpenDoorResponse {
  doorId: string;
  newState: string;
  revealedRoom: string | null;
  placementInstruction: string;
  log: string[];
}
export const openDoor = call<OpenDoorRequest, OpenDoorResponse>("open_door");

// ---- searchTreasure ----

export interface SearchTreasureRequest {
  gameId: string;
  heroId: string;
  roomId: string;
  wanderingMonsterDrawn?: boolean;
}
export interface MonsterAttack {
  monsterName: string;
  heroName: string;
  diceRolled: number;
  skulls: number;
}
/** A chest or tomb that went off because the room was searched for
 * treasure before it was searched for traps. */
export interface FurnitureTrap {
  trapId?: string;
  furnitureType: string;
  type: string;
  pos: Coord;
}
export interface SearchTreasureResponse {
  roomId: string;
  /** False when trapped furniture sprang instead -- no card is drawn,
   * the turn ends, and the search isn't spent. */
  treasureDrawn: boolean;
  sprungFurnitureTraps: FurnitureTrap[];
  spawnedMonster: { type: string; pos: Coord; attacksImmediately: boolean; placementInstruction: string } | null;
  monsterAttack: MonsterAttack | null;
  log: string[];
}
export const searchTreasure = call<SearchTreasureRequest, SearchTreasureResponse>("search_treasure");

// ---- searchTrapsAndSecretDoors ----

export interface SearchTrapsAndSecretDoorsRequest {
  gameId: string;
  heroId: string;
  roomId: string;
  /** Two DISTINCT hero actions in the 1989 rules -- pick one. */
  searchType: "traps" | "secret_doors";
}
export interface FoundTrap {
  trapId: string;
  type: string;
  pos: Coord;
  placementInstruction: string;
}
export interface FoundSecretDoor {
  doorId: string;
  squares: Coord[];
  placementInstruction: string;
}
export interface SearchTrapsAndSecretDoorsResponse {
  roomId: string;
  /** Trapped chests/tombs spotted -- knowing about them is what keeps a
   * later treasure search from setting the room off. */
  foundFurnitureTraps: FurnitureTrap[];
  foundTraps: FoundTrap[];
  foundSecretDoors: FoundSecretDoor[];
  log: string[];
}
export const searchTrapsAndSecretDoors = call<SearchTrapsAndSecretDoorsRequest, SearchTrapsAndSecretDoorsResponse>(
  "search_traps_and_secret_doors"
);

// ---- castSpell ----

export interface CastSpellRequest {
  gameId: string;
  heroId: string;
  spellId: string;
  targetMonsterId?: string;
  targetHeroId?: string;
  /** Genie only: which door to throw open. */
  doorId?: string;
  /** Genie only: "door" or "attack". */
  genieMode?: "door" | "attack";
}
export interface CastSpellResponse {
  spellId: string;
  spellName: string;
  monsterDamage: Record<string, number>;
  monsterStatuses: { monsterId: string; status: string; missesTurns: number }[];
  heroStatuses: { heroId: string; status: string; consumedByMove: boolean; playerCleared: boolean }[];
  openedDoorId: string | null;
  log: string[];
}
export const castSpell = call<CastSpellRequest, CastSpellResponse>("cast_spell");

// ---- resolveTrapAction ----

export type CombatDieFace = "skull" | "white_shield" | "black_shield";

export interface ResolveTrapActionRequest {
  gameId: string;
  heroId: string;
  trapId: string;
  action: "jump" | "disarm" | "step";
  /** The hero's own die, reported -- the app never rolls it. */
  dieFace?: CombatDieFace;
  landing?: Coord;
  /** Inventory is physical, so the player asserts this. */
  hasToolKit?: boolean;
}
export interface ResolveTrapActionResponse {
  trapId: string;
  action: string;
  sprung: boolean;
  disarmed: boolean;
  heroPos: Coord;
  placementInstruction: string | null;
  log: string[];
}
export const resolveTrapAction = call<ResolveTrapActionRequest, ResolveTrapActionResponse>(
  "resolve_trap_action_endpoint"
);

// ---- endTurn ----

export interface EndTurnRequest {
  gameId: string;
}
export interface EndTurnResponse {
  phase: string;
  heroPhaseSegment: number;
}
export const endTurn = call<EndTurnRequest, EndTurnResponse>("end_turn");

// ---- rollZargonTurnType ----

export interface RollZargonTurnTypeRequest {
  gameId: string;
}
export interface RollZargonTurnTypeResponse {
  turnType: "normal" | "cunning" | "wandering";
  needsCunningPrompt: boolean;
  heroes: { id: string; name: string }[];
}
export const rollZargonTurnType = call<RollZargonTurnTypeRequest, RollZargonTurnTypeResponse>("roll_zargon_turn_type");

// ---- resolveZargonTurn ----

export interface ResolveZargonTurnRequest {
  gameId: string;
  turnType: "normal" | "cunning" | "wandering";
  lowestBpHeroId?: string;
}
export interface MonsterResult {
  monsterId: string;
  monsterName: string;
  action: string;
  endPos: Coord | null;
  attackedHeroName: string | null;
  skulls: number | null;
}
/** A Chaos spell a monster spent this turn. Hero damage is announced,
 * never tracked -- Body Points live on the physical hero sheet. */
export interface ChaosCast {
  monsterId: string;
  monsterName: string;
  spellId: string;
  spellName: string;
  heroHits: { heroId: string; heroName: string; damage: number; reductionDice: number }[];
  statuses: { heroId: string; heroName: string; status: string; missesTurns: number }[];
  summons: { type: string; pos: Coord }[];
}
export interface ResolveZargonTurnResponse {
  turnType: string;
  monsterResults: MonsterResult[];
  spawnedMonster: { type: string; pos: Coord; attacksImmediately: boolean; placementInstruction: string } | null;
  chaosCasts: ChaosCast[];
  log: string[];
}
export const resolveZargonTurn = call<ResolveZargonTurnRequest, ResolveZargonTurnResponse>("resolve_zargon_turn");

// ---- resolveHeroAttack ----

export interface ResolveHeroAttackRequest {
  gameId: string;
  monsterId: string;
  skulls: number;
}
export interface ResolveHeroAttackResponse {
  monsterName: string;
  diceRolled: number;
  blocks: number;
  skullsFaced: number;
  damage: number;
  bodyPointsBefore: number;
  bodyPointsAfter: number;
  defeated: boolean;
  log: string;
}
export const resolveHeroAttack = call<ResolveHeroAttackRequest, ResolveHeroAttackResponse>("resolve_hero_attack");

// ---- recordHeroDefense ----

export interface RecordHeroDefenseRequest {
  gameId: string;
  heroId: string;
  skullsFaced: number;
  shieldsReported: number;
  /** Which queued prompt this answers (game state's pendingDefenses). */
  defenseId?: string;
}
export interface RecordHeroDefenseResponse {
  log: string;
}
export const recordHeroDefense = call<RecordHeroDefenseRequest, RecordHeroDefenseResponse>("record_hero_defense");

// ---- recordHeroDeath ----

export interface RecordHeroDeathRequest {
  gameId: string;
  heroId: string;
}
export interface RecordHeroDeathResponse {
  heroId: string;
  heroName: string;
  partyWiped: boolean;
  log: string[];
}
export const recordHeroDeath = call<RecordHeroDeathRequest, RecordHeroDeathResponse>("record_hero_death");

// ---- undoLastAction ----

export interface UndoLastActionRequest {
  gameId: string;
}
export interface UndoLastActionResponse {
  /** What was rolled back, e.g. "the hero's move". */
  label: string;
  /** Steps still available after this one. */
  undoDepth: number;
}
export const undoLastAction = call<UndoLastActionRequest, UndoLastActionResponse>("undo_last_action");

// ---- attemptBreakSpell ----

export interface AttemptBreakSpellRequest {
  gameId: string;
  heroId: string;
  /** The hero rolls one red die per Mind Point (both physical) and
   * reports whether a 6 came up. */
  rolledSix: boolean;
}
export interface AttemptBreakSpellResponse {
  broke: boolean;
  log: string[];
}
export const attemptBreakSpell = call<AttemptBreakSpellRequest, AttemptBreakSpellResponse>("attempt_break_spell");
