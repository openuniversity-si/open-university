/** A compared region: a Figma node inside the frame's exported root and the DOM element that implements it. */
export interface FidelityRegion {
  readonly name: string;
  /** Node id inside the frame root (instance children included, e.g. `I24:145;21:4`); its box comes from the active set. */
  readonly figmaNodeId: string;
  /** Stable selector, normally `[data-testid="…"]`. */
  readonly selector: string;
  /** Solid-area coordinates relative to the region, in CSS pixels. */
  readonly colorSamples: readonly { readonly x: number; readonly y: number }[];
  /** A rail card may extend beyond the exported canvas; compare its visible pixels and full DOM geometry. */
  readonly clipToFrame?: boolean;
  /** Daniel-approved course-name row delta only; pixels still crop from the original reference. */
  readonly precedingLabelRows?: number;
  /** Compare this named child of the instance instead (F11: a Continue card's "Cover 9:16" or "Meta"; ids differ per variant). */
  readonly figmaChild?: string;
  /** The static card instance includes 2px top padding; compare its poster child instead. */
  readonly posterBox?: boolean;
  /** D1 signed-out differences only: checks, elapsed time and scrubber. */
  readonly signedOutMasks?: readonly string[];
}

export const FIDELITY_REGION_ROLES = [
  "TopNav", "BillboardText", "PrimaryCTA", "CourseCard", "RailHeader", "About",
  "Lectures", "LecturesHeader", "PlaylistItem", "CourseAbout", "MoreFromAuthor",
  "PlayerFrame", "Scrubber", "PlayerActions", "PlayerRailTop", "PlayerRailEnd",
  "AccountMenu", "SignInFeedback", "Footer",
] as const;
