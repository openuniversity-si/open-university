/** Addendum 2.5: the footer goes from Hidden to Visible over the last 80 px of the page. */
export const FOOTER_FADE_DISTANCE = 80;

export function smoothstep(t: number): number {
  const clamped = Math.min(Math.max(t, 0), 1);
  return clamped * clamped * (3 - 2 * clamped);
}

/** `opacity = smoothstep(clamp(1 − distanceToPageEnd / 80, 0, 1))`; reduced motion shows the footer at once. */
export function footerOpacity(distanceToPageEnd: number, reducedMotion: boolean): number {
  if (reducedMotion) return 1;
  return smoothstep(1 - Math.max(distanceToPageEnd, 0) / FOOTER_FADE_DISTANCE);
}

/** Distance from the bottom edge of the viewport to the end of the document, never negative. */
export function distanceToPageEnd(scrollHeight: number, scrollY: number, viewportHeight: number): number {
  return Math.max(scrollHeight - scrollY - viewportHeight, 0);
}
