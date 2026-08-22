/**
 * The 1989 base game's twelve hero spell cards, mirroring
 * functions/data/hero_spells.json (transcribed from the owner's cards).
 *
 * The client needs the names, the elements and enough shape to build a
 * sensible form -- who a card targets, and whether the Genie is being
 * asked to open a door or attack. Resolution lives on the server.
 */

export type SpellTarget = "hero" | "monster" | "choice";

export interface HeroSpellCard {
  id: string;
  name: string;
  element: string;
  target: SpellTarget;
  /** One line of what the card does, for the panel. */
  summary: string;
}

export const SPELL_ELEMENTS = ["Air", "Earth", "Fire", "Water"] as const;

export const HERO_SPELL_CARDS: HeroSpellCard[] = [
  { id: "swift_wind", name: "Swift Wind", element: "Air", target: "hero", summary: "Double red dice on that hero's next move." },
  { id: "tempest", name: "Tempest", element: "Air", target: "monster", summary: "That monster misses its next turn." },
  { id: "genie", name: "Genie", element: "Air", target: "choice", summary: "Open any door on the board, or attack with 5 combat dice." },
  { id: "heal_body", name: "Heal Body", element: "Earth", target: "hero", summary: "Restore up to 4 lost Body Points." },
  { id: "rock_skin", name: "Rock Skin", element: "Earth", target: "hero", summary: "One extra defend die until that hero takes damage." },
  { id: "pass_through_rock", name: "Pass Through Rock", element: "Earth", target: "hero", summary: "That hero's next move goes through walls." },
  { id: "courage", name: "Courage", element: "Fire", target: "hero", summary: "Two extra attack dice on that hero's next attack." },
  { id: "ball_of_flame", name: "Ball of Flame", element: "Fire", target: "monster", summary: "2 Body Points, less the monster's own save roll." },
  { id: "fire_of_wrath", name: "Fire of Wrath", element: "Fire", target: "monster", summary: "1 Body Point unless the monster rolls a 5 or 6." },
  { id: "water_of_healing", name: "Water of Healing", element: "Water", target: "hero", summary: "Restore up to 4 lost Body Points." },
  { id: "sleep", name: "Sleep", element: "Water", target: "monster", summary: "Holds a monster -- no moving, attacking or defending. Not the undead." },
  { id: "veil_of_mist", name: "Veil of Mist", element: "Water", target: "hero", summary: "That hero's next move passes through monsters." },
];

export function spellsForElements(elements: string[] | undefined): HeroSpellCard[] {
  const wanted = new Set((elements ?? []).map((e) => e.toLowerCase()));
  return HERO_SPELL_CARDS.filter((card) => wanted.has(card.element.toLowerCase()));
}

export function spellCard(id: string): HeroSpellCard | undefined {
  return HERO_SPELL_CARDS.find((card) => card.id === id);
}
