import type { GeometryBox } from "./compare.ts";

/**
 * F08 gate exceptions (A Torre, 9 Oct 2026 04:30 BRT, under Daniel's standing order to run serially).
 * Each entry is region-specific and backed by a decision of Daniel that outranks the static 154:* frames.
 * Limits in FIDELITY_LIMITS are untouched: no global tolerance increase. Everything not listed is compared.
 */
export interface GateException {
  readonly id: string;
  readonly phase: "F08" | "F11";
  readonly region: string;
  readonly reason: string;
}

const F08_EXCEPTIONS: readonly GateException[] = [
  {
    id: "kicker-full-course-name",
    phase: "F08",
    region: "LessonHeader",
    reason:
      "Daniel decision 5 (full course name in the Player kicker). Static frames say 'GENESIS'. Only the kicker row is not pixel-compared; " +
      "title and meta are compared below it. On 390 px the kicker wraps to a second 17 px line (Kicker node height): that single line is " +
      "removed from geometry for LessonHeader and the regions after it, and only when the measured header growth is 17±1 px.",
  },
  {
    id: "approved-catalog-meta",
    phase: "F08",
    region: "PlayerRail",
    reason:
      "Approved catalog JSON (durations/labels) beats static rail text. Only each row's one-line 'Meta' node (e.g. 'Lecture 1 · 2h 38m') " +
      "is masked, except the Now playing row, which PlaylistNowPlaying still compares in full.",
  },
];

/** F11's signed-in Player frames (43:662/53:1518/42:554) carry the same static kicker and rail text; same decisions, same scope. */
export const GATE_EXCEPTIONS: readonly GateException[] = [...F08_EXCEPTIONS, ...F08_EXCEPTIONS.map((entry) => ({ ...entry, phase: "F11" as const }))];

export const KICKER_LINE = 17;
const REGIONS_AFTER_HEADER = new Set(["PlayerActions", "PlayerRail", "PlayerRailHeader", "PlayerRailProgress", "PlaylistNowPlaying", "PlayerRailEnd", "Footer", "LectureAbout"]);

interface SetNode extends GeometryBox { readonly rootNodeId: string; readonly nodeId: string; readonly name: string }

export function hasException(phase: string, region: string, id: string): boolean {
  return GATE_EXCEPTIONS.some((entry) => entry.phase === phase && entry.region === region && entry.id === id);
}

/** Approved kicker wrap: 17 px on mobile only when the measured LessonHeader growth matches one kicker line. */
export function kickerWrapDelta(phase: string, viewport: number, referenceHeader?: GeometryBox, siteHeader?: GeometryBox): number {
  if (!hasException(phase, "LessonHeader", "kicker-full-course-name") || viewport !== 390 || !referenceHeader || !siteHeader) return 0;
  return Math.abs(siteHeader.height - referenceHeader.height - KICKER_LINE) <= 1 ? KICKER_LINE : 0;
}

export function shiftedByKicker(region: string): boolean { return REGIONS_AFTER_HEADER.has(region); }

/** Extra reference-relative masks for a region (absolute node boxes; caller makes them relative). */
export function exceptionMaskNodes(phase: string, region: string, nodes: readonly SetNode[], regionNodeId: string): readonly SetNode[] {
  if (region === "PlayerRail" && hasException(phase, region, "approved-catalog-meta")) {
    const nowPlayingRows = new Set(nodes.filter((node) => node.name === "Status/Now playing").map((node) => node.nodeId.split(";").slice(0, 2).join(";")));
    return nodes.filter((node) => node.name === "Meta" && node.nodeId.startsWith(`I${regionNodeId};`) && !nowPlayingRows.has(node.nodeId.split(";").slice(0, 2).join(";")));
  }
  return [];
}
