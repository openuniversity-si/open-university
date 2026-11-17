import type { PublicCatalog } from "./release.ts";
import { homeRowSpec } from "./home-row-kind.ts";
import { resolveCover } from "./cover-resolve.ts";

const hasOwnCover = (cover: unknown) => resolveCover({ institution: cover ? [{ kind: "poster_9x16" }] : [] }, { target: "institution" }) !== undefined;

/**
 * Cover direction (Daniel, 22/10/2026; docs/catalog/cover-hierarchy.md, ADR-40).
 * A cover may be inherited only downward: lesson from course, course from its subarea.
 * A university (curated Home row) and an author on the Authors tab never borrow a course poster.
 * Messages name the row. The compiler enforces university covers; the admin release cutter also enforces authors. The stored-row rule (PUT /home, bundle apply, ship) is `rules/home.ts`.
 */

/** A release row that actually shows: it publishes at least one course. Empty rows are not on the tab. */
export function releaseCoverErrors(catalog: PublicCatalog, scope: "university" | "all"): string[] {
  const universities = catalog.home.rows.filter((row) => homeRowSpec(row.kind).cover === "own" && row.courseIds.length > 0 && !hasOwnCover(row.cover))
    .map((row) => `Curated row ${row.id} needs a cover.`);
  if (scope === "university") return universities;
  const authors = catalog.home.rows.filter((row) => homeRowSpec(row.kind).cover === "author" && row.courseIds.length > 0).flatMap((row) => {
    const author = catalog.authors.find((entry) => entry.id === row.authorId);
    return author && !hasOwnCover(author.cover) ? [`Author row ${row.id} needs a cover on ${author.id}.`] : [];
  });
  return [...universities, ...authors];
}

export function assertReleaseCovers(catalog: PublicCatalog, scope: "university" | "all"): void {
  const errors = releaseCoverErrors(catalog, scope);
  if (errors.length > 0) throw new Error(errors.join(" "));
}
