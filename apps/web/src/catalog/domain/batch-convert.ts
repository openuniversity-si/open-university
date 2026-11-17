import type { CourseBundleV1 } from "./bundle.ts";
import { catalogBatchV2Schema, type CatalogBatchV2 } from "./schema/batch-v2.ts";

/** One v1 bundle and the content address of each of its cover files (prepared as tower-media uploads them). */
export interface V1Entry { readonly file: string; readonly bundle: CourseBundleV1; readonly coverShas: Readonly<Record<string, string>> }

export type Converted = { readonly ok: true; readonly batch: CatalogBatchV2 } | { readonly ok: false; readonly failures: readonly string[] };

/**
 * A directory of CourseBundleV1 files as one CatalogBatchV2 (S07). The offering institution (D-024) is the fact the v1
 * data holds: the institution of the University row the bundle is placed on (`rowInstitutions`, read from the catalog),
 * else an author of kind institution. A person author placed on no row has no institution fact: the course is a
 * failure, never a guess. Institutions and sources are not emitted: the planner resolves them from the catalog.
 * Every failure is listed.
 */
export function batchFromBundlesV1(entries: readonly V1Entry[], rowInstitutions: ReadonlyMap<string, string>): Converted {
  const failures: string[] = [];
  const lecturers = new Map<string, CourseBundleV1["author"]>();
  const courses = [];
  for (const { file, bundle, coverShas } of entries) {
    const { author, course, home } = bundle;
    const institutionId = home ? rowInstitutions.get(home.rowId) : author.kind === "institution" ? author.id : undefined;
    if (home && !institutionId) failures.push(`${file}: row ${home.rowId} has no institution in the catalog.`);
    if (!home && !institutionId) failures.push(`${file}: course ${course.id} is on no University row and its author ${author.id} is a ${author.kind}; name its institution (D-024).`);
    if (author.kind !== "institution") {
      const known = lecturers.get(author.id);
      if (known && JSON.stringify(known) !== JSON.stringify(author)) failures.push(`${file}: lecturer ${author.id} differs from another bundle.`);
      lecturers.set(author.id, author);
    }
    const covers = bundle.covers.flatMap((cover) => {
      const sha = coverShas[cover.kind];
      if (!sha) { failures.push(`${file}: cover ${cover.kind} (${cover.path}) has no content address.`); return []; }
      return [{ kind: cover.kind, sha }];
    });
    courses.push({ institutionId: institutionId ?? author.id, homeRowId: home?.rowId ?? null, course, editions: bundle.editions, lessons: bundle.lessons, texts: bundle.texts, covers });
  }
  if (entries.length === 0) failures.push("The directory has no bundle.");
  if (failures.length > 0) return { ok: false, failures };
  const parsed = catalogBatchV2Schema.safeParse({
    version: 2,
    lecturers: [...lecturers.values()].map(({ id, slug, name, monogram, kind }) => ({ id, slug, name, monogram, kind })),
    courses,
  });
  return parsed.success ? { ok: true, batch: parsed.data } : { ok: false, failures: parsed.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`) };
}
