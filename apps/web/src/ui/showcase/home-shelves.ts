import type { BillboardView, RailView } from "@/catalog/domain/view-model.ts";
import { continueWatchingTitle } from "@/site/domain/reader-copy.ts";

/** One shelf `BillboardSelection` paints. `resume` cards carry the lesson the viewer would continue. */
export interface HomeShelf {
  readonly id: string;
  readonly title: string;
  readonly courses: readonly BillboardView[];
  readonly resume: boolean;
}

/**
 * The shelves a Home paints. A non-empty resume list is shelf zero, id `continue-watching`.
 * Published rails keep the order they were given. The signed-in Home passes an empty rail list.
 */
export function homeShelves(rails: readonly RailView[], resume: readonly BillboardView[] = []): readonly HomeShelf[] {
  const first = resume.length > 0 ? [{ id: "continue-watching", title: continueWatchingTitle, courses: resume, resume: true }] : [];
  return [...first, ...rails.map((rail) => ({ id: rail.id, title: rail.title, courses: rail.courses, resume: false }))];
}
