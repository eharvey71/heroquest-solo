/**
 * The 1989 base game's hero spell cards, by element.
 *
 * NAMES ONLY, deliberately. The cards themselves stay physical
 * (CLAUDE.md's boundary): the app doesn't know what any of them does,
 * so the player still reports the dice an attack spell rolls. What this
 * buys is the difference between typing "Ball of Flame" correctly and
 * picking it off a list -- and, since the app tracks spellsCast, seeing
 * at a glance which cards are already spent.
 *
 * TRANSCRIBED FROM MEMORY OF THE 1989 NA SET, NOT FROM THE OWNER'S
 * CARDS. If a name here is wrong, it is wrong in the dropdown -- correct
 * it and it is fixed everywhere.
 *
 * The Wizard takes three elements (nine cards) and the Elf one (three)
 * at the start of a quest; the app doesn't ask which, so both casters
 * see all twelve and the player picks the card in their hand.
 */

export interface SpellElement {
  element: string;
  spells: string[];
}

export const HERO_SPELL_ELEMENTS: SpellElement[] = [
  { element: "Air", spells: ["Genie", "Swift Wind", "Tempest"] },
  { element: "Earth", spells: ["Heal Body", "Pass Through Rock", "Rock Skin"] },
  { element: "Fire", spells: ["Ball of Flame", "Courage", "Fire of Wrath"] },
  { element: "Water", spells: ["Sleep", "Veil of Mist", "Water of Healing"] },
];
