// Code points of public/fonts/Inter.woff2, mirrored from scripts/fonts/inter-unicodes.txt (charset.test.ts keeps them equal).
// These are the characters the page can draw. Slot length stays with the offer.

export const INTER_SUBSET: readonly (readonly [number, number])[] = [
  [0x0020, 0x007E], [0x00A0, 0x00FF], [0x0131, 0x0131], [0x0152, 0x0153], [0x02C6, 0x02C6], [0x02DA, 0x02DA], [0x02DC, 0x02DC],
  [0x2009, 0x200A], [0x2010, 0x2014], [0x2018, 0x201A], [0x201C, 0x201E], [0x2022, 0x2022], [0x2026, 0x2026], [0x2030, 0x2030],
  [0x2032, 0x2033], [0x2039, 0x203A], [0x2044, 0x2044], [0x20AC, 0x20AC], [0x2122, 0x2122], [0x2190, 0x2193], [0x2212, 0x2212],
  [0x2248, 0x2248], [0x2260, 0x2260], [0x2264, 0x2265],
];

export function inInterSubset(codePoint: number): boolean {
  return INTER_SUBSET.some(([first, last]) => codePoint >= first && codePoint <= last);
}

/** Distinct characters of `text` the page cannot draw, as `U+XXXX` (never the surrounding text). */
export function outsideInterSubset(text: string): string[] {
  const missing = new Set<string>();
  for (const character of text) {
    const point = character.codePointAt(0) ?? 0;
    if (!inInterSubset(point)) missing.add(`U+${point.toString(16).toUpperCase().padStart(4, "0")}`);
  }
  return [...missing];
}

/** The site refuses a text the page cannot draw. Null when every character is in the subset. */
export function undrawablePageText(kind: string, field: string, text: string): string | null {
  const missing = outsideInterSubset(text);
  if (missing.length === 0) return null;
  return `${kind}.${field} uses characters outside the Inter subset: ${missing.join(", ")}.`;
}
