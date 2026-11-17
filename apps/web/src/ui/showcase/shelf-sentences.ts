import type { BillboardView } from "@/catalog/domain/view-model";
import {
  areaNoun,
  authorCoverKind,
  courseNoun,
  creditsNote,
  metaDot,
  metaGap,
  universityCoverKind,
  universityKicker,
  universityNoun,
  universityNounMany,
} from "@/site/domain/reader-copy.ts";

/** A count and its noun, the way the shelf has always said it ("1 course", "2 courses"). */
export const plural = (n: number, one: string, many = `${one}s`): string => `${String(n)} ${n === 1 ? one : many}`;

/** One sentence for every image, shown once at the top of /credits. */
export const CREDITS_NOTE = creditsNote;

export type CoverCreditKind = "university" | "author";

/** The label a credit row paints. The shelf stores the kind, not this sentence. */
export function coverKindLabel(kind: CoverCreditKind): string {
  return kind === "university" ? universityCoverKind : authorCoverKind;
}

/** "17 universities  ·  311 courses" (each course counted once). */
export function countryMeta(group: { readonly universityCount: number; readonly courseCount: number }): string {
  return `${plural(group.universityCount, universityNoun, universityNounMany)}${metaGap}${plural(group.courseCount, courseNoun)}`;
}

/** Counts, the published name, and the university's own cover. The sentence is not in here. */
export interface ShelfFigure {
  readonly slug: string;
  readonly name: string;
  readonly fullName: string;
  readonly place: string;
  readonly cover: { readonly url: string; readonly width: number; readonly height: number } | null;
  readonly courseCount: number;
  readonly areaCount: number;
  /** The release names areas, so the hero counts them. */
  readonly areasNamed: boolean;
}

/**
 * Billboard of one university. A 9:16 cover in a 16:9 hero: full width, shifted to its upper half (the building),
 * never stretched. The figure is that university's own cover.
 */
export function universityHero(entry: ShelfFigure): BillboardView {
  const meta = [plural(entry.courseCount, courseNoun), ...(entry.areasNamed ? [plural(entry.areaCount, areaNoun)] : []), ...(entry.place ? [entry.place] : [])].join(metaGap);
  const art = entry.cover ? { url: entry.cover.url, width: entry.cover.width, height: entry.cover.height } : null;
  return {
    id: `university-${entry.slug}`, slug: entry.slug, title: entry.fullName, displayTitle: entry.name,
    billboardDescription: entry.fullName, billboardDescriptionMobile: entry.fullName,
    author: [entry.place.toUpperCase(), universityKicker].filter((part) => part !== "").join(metaDot),
    featured: false, meta, metaMobile: meta, startHref: `/universities/${entry.slug}`,
    assets: art ? { heroDesktop: { ...art, transform: [[1, 0, 0], [0, 1, 0.25]] }, heroMobile: { ...art, transform: null } } : {},
  };
}
