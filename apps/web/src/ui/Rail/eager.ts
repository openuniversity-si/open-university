/**
 * Posters in the initial HTML (P8, ADR-23): only the first EAGER_ROWS row (the one under the hero on a phone; the second row is below
 * the fold at 390 px and loading it eagerly took bandwidth from the hero, the LCP), and in them only the cards that fit the viewport.
 * Everything else is a LazyPoster, requested near the viewport. Derived from the rail tokens (card width, gap, gutter)
 * at each breakpoint's design width; eager.test.ts keeps these numbers in sync with the CSS.
 */
export const EAGER_ROWS = 1;

/** Cards visible (even partially) in a rail at 390 (mobile), 768 (tablet, mobile card) and 1920 (desktop). */
export const EAGER_CARDS_PER_ROW = { mobile: 3, tablet: 5, desktop: 9 } as const;

/**
 * The HTML is the same for every viewport, so it carries only the cards visible at the narrowest one; the extra cards a
 * wider viewport shows load on demand right after hydration (they are already in view).
 */
export const EAGER_CARDS_IN_HTML = Math.min(...Object.values(EAGER_CARDS_PER_ROW));

/** Row and card are 0-based, in DOM order (Continue Watching counts as a row when present). */
export function isEagerPoster(row: number, card: number): boolean {
  return row < EAGER_ROWS && card < EAGER_CARDS_IN_HTML;
}
