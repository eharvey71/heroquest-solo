/**
 * A side quest, played on its own page: the passage, its choices, the
 * die prompt for a choice with a test, and -- once a terminal is
 * reached -- the epilogue and what it changed, held on screen until
 * the player chooses to go back. The server (functions/main.py
 * advance_side_quest) is the only thing that decides where a choice
 * leads and what it does; this component shows and asks.
 *
 * Why the epilogue is held here rather than read off the game doc: the
 * write that applies a terminal's effects also clears
 * pendingSideQuest, so the moment the scene ends the game doc says
 * there is no scene -- if this page vanished on that snapshot, the
 * player would never see how it ended. See design/side-quests-design.md
 * section 12.
 */

import { useState } from "react";
import { squareKey } from "../lib/board";
import type { GameState, SideQuestProgress } from "../lib/gameState";
import type { SideQuestReport } from "../lib/functionsClient";
import type { SideQuest, SideQuestChoice } from "../lib/useQuestMap";
import { spellsForElements } from "../data/heroSpells";

export interface SceneEpilogue {
  sideQuestId: string;
  title: string;
  outcome: "success" | "partial" | "failure" | null;
  lines: string[];
}

interface SideQuestViewProps {
  sideQuest: SideQuest;
  progress: SideQuestProgress | undefined;
  game: GameState;
  busy: boolean;
  /** Set once the scene has ended; the page then shows the epilogue
   * instead of a passage. */
  epilogue: SceneEpilogue | null;
  /** runAction's last error -- the page covers the rail where it would
   * otherwise show. */
  error?: string | null;
  onChoose: (choiceId: string, report?: SideQuestReport) => void;
  onClose: () => void;
}

const SETTING_LABEL: Record<string, string> = {
  town: "In town",
  forest: "In the forest",
  cave: "Below, in the caves",
  shrine: "At a shrine",
  road: "On the road",
  vision: "A vision",
};

const OUTCOME_LABEL: Record<string, string> = {
  success: "A success",
  partial: "A partial success",
  failure: "A failure",
};

const HERO_NAME: Record<string, string> = { barbarian: "Barbarian", dwarf: "Dwarf", elf: "Elf", wizard: "Wizard" };

/** The client's mirror of engine/side_quests.choice_visible -- the
 * server is the one that counts; this just keeps the page honest. */
export function isChoiceVisible(
  choice: SideQuestChoice,
  game: GameState,
  progress: SideQuestProgress | undefined,
  sideQuest: SideQuest
): boolean {
  const living = game.heroes.filter((h) => h.alive !== false);
  if (choice.requiresHero && !living.some((h) => h.id === choice.requiresHero)) return false;
  if (choice.requiresElement) {
    const spent = new Set(game.spellsCast ?? []);
    const held = living.some((h) =>
      spellsForElements(game.spellbooks?.[h.id]).some(
        (card) => card.element.toLowerCase() === choice.requiresElement?.toLowerCase() && !spent.has(card.id)
      )
    );
    if (!held) return false;
  }
  if (choice.requiresFlag && !(progress?.flags ?? []).includes(choice.requiresFlag)) return false;
  const retry = sideQuest.retry;
  if (retry && progress?.retried && progress.passageId === retry.from) {
    const targets = choice.test ? [choice.test.success, choice.test.failure] : [choice.next];
    if (targets.includes(retry.to)) return false;
  }
  return true;
}

/** Where the party is standing, for a room-hooked scene's Begin button. */
export function heroInRoom(game: GameState, room: string | undefined, areaOf: Map<string, string>): boolean {
  if (!room) return false;
  return game.heroes.some((h) => h.alive !== false && areaOf.get(squareKey(h.pos[0], h.pos[1])) === room);
}

export function SideQuestView({ sideQuest, progress, game, busy, epilogue, error, onChoose, onClose }: SideQuestViewProps) {
  // The choice whose die the player is now rolling at the table.
  const [pendingTest, setPendingTest] = useState<SideQuestChoice | null>(null);

  const passageId = progress?.status === "active" && progress.passageId ? progress.passageId : sideQuest.start;
  const passage = sideQuest.passages[passageId];
  const passageCount = Object.keys(sideQuest.passages).length;
  const stepsTaken = progress?.history?.length ?? 0;

  const pick = (choice: SideQuestChoice) => {
    if (choice.test && choice.test.kind !== "zargon") {
      setPendingTest(choice);
      return;
    }
    onChoose(choice.id);
  };

  const report = (r: SideQuestReport) => {
    if (!pendingTest) return;
    const id = pendingTest.id;
    setPendingTest(null);
    onChoose(id, r);
  };

  return (
    <div className="scene-overlay" role="dialog" aria-label={sideQuest.title}>
      <div className="scene-card">
        <p className="scene-kicker">
          Side quest &middot; {SETTING_LABEL[sideQuest.setting] ?? sideQuest.setting}
          {sideQuest.kind === "required" ? " · required" : ""}
        </p>
        <h2>{sideQuest.title}</h2>
        {error && <p style={{ color: "#e66" }}>Error: {error}</p>}

        {epilogue ? (
          <div className="scene-epilogue">
            <p className="scene-kicker">{OUTCOME_LABEL[epilogue.outcome ?? ""] ?? "The scene ends"}</p>
            <ul>
              {epilogue.lines.map((line, i) => (
                <li key={i}>{line.replace(/^\[[^\]]*\]\s*/, "")}</li>
              ))}
            </ul>
            <button className="primary" onClick={onClose}>
              Back to the dungeon
            </button>
          </div>
        ) : !passage ? (
          <p className="hint">This scene has lost its place. Undo the last step from the header.</p>
        ) : (
          <>
            <p className="hint">
              Passage {Math.min(stepsTaken + 1, passageCount)} of at most {passageCount}. The board waits; nothing
              moves while you are away.
            </p>
            <p className="scene-text">{passage.text}</p>

            {pendingTest?.test ? (
              <div className="alert scene-test">
                <p className="alert-title">Roll at the table</p>
                <TestPrompt choice={pendingTest} busy={busy} onReport={report} onCancel={() => setPendingTest(null)} />
              </div>
            ) : (
              <div className="scene-choices">
                {passage.choices.filter((c) => isChoiceVisible(c, game, progress, sideQuest)).map((choice) => (
                  <button key={choice.id} onClick={() => pick(choice)} disabled={busy}>
                    {choice.label}
                    <ChoiceNote choice={choice} />
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function ChoiceNote({ choice }: { choice: SideQuestChoice }) {
  const notes: string[] = [];
  if (choice.requiresHero) notes.push(`${HERO_NAME[choice.requiresHero] ?? choice.requiresHero} only`);
  if (choice.requiresElement) notes.push(`needs an unspent ${choice.requiresElement} spell`);
  const t = choice.test;
  if (t?.kind === "combat_dice") notes.push(`roll ${t.dice} combat ${t.dice === 1 ? "die" : "dice"}: ${t.needSkulls}+ skull${t.needSkulls === 1 ? "" : "s"}`);
  if (t?.kind === "mind") notes.push("Mind Point roll");
  if (t?.kind === "body") notes.push("Body Point roll");
  if (t?.kind === "zargon") notes.push(`Zargon rolls ${t.dice} combat ${t.dice === 1 ? "die" : "dice"}`);
  if (notes.length === 0) return null;
  return <span className="scene-choice-note">{notes.join(" · ")}</span>;
}

function TestPrompt({
  choice,
  busy,
  onReport,
  onCancel,
}: {
  choice: SideQuestChoice;
  busy: boolean;
  onReport: (r: SideQuestReport) => void;
  onCancel: () => void;
}) {
  const t = choice.test!;
  if (t.kind === "combat_dice") {
    const counts = Array.from({ length: t.dice + 1 }, (_, i) => i);
    return (
      <div className="panel-stack">
        <span>
          <strong>{choice.label}</strong> &mdash; roll {t.dice} combat {t.dice === 1 ? "die" : "dice"} and report the
          skulls. {t.needSkulls} or more succeeds.
        </span>
        <div className="panel-row">
          <span className="hint">Skulls rolled:</span>
          <div className="shield-count-row">
            {counts.map((n) => (
              <button key={n} onClick={() => onReport({ skulls: n })} disabled={busy}>
                {n}
              </button>
            ))}
          </div>
          <button className="quiet" onClick={onCancel} disabled={busy}>
            Back
          </button>
        </div>
      </div>
    );
  }
  const stat = t.kind === "mind" ? "Mind" : "Body";
  return (
    <div className="panel-stack">
      <span>
        <strong>{choice.label}</strong> &mdash; roll one red die against your {stat} Points. Under or equal succeeds.
        The app never needs the number, only how it went.
      </span>
      <div className="panel-row">
        <button className="primary" onClick={() => onReport({ passed: true })} disabled={busy}>
          Passed
        </button>
        <button onClick={() => onReport({ passed: false })} disabled={busy}>
          Failed
        </button>
        <button className="quiet" onClick={onCancel} disabled={busy}>
          Back
        </button>
      </div>
    </div>
  );
}
