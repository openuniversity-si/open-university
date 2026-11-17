import type { Queryable } from "../../platform/db/uow.ts";

export interface CatalogLifecycleRef {
  readonly sha256: string;
  readonly retainedRelease: boolean;
}

const SHA = /[a-f0-9]{64}/g;

function shas(value: unknown): string[] {
  return typeof value === "string" ? (value.match(SHA) ?? []) : [];
}

/** Authors, home rows (including og inside the cover JSON) and restorable releases. */
export async function previewCourseCount(db: Queryable): Promise<number> {
  const { rows } = await db.query("SELECT count(*)::int AS n FROM courses");
  return Number(rows[0]?.n ?? 0);
}

export async function catalogLifecycleRefs(db: Queryable): Promise<{ complete: boolean; refs: CatalogLifecycleRef[] }> {
  try {
    const authors = await db.query("SELECT cover::text AS cover FROM authors");
    const home = await db.query("SELECT cover::text AS cover FROM home_rows");
    const releases = await db.query("SELECT is_active, payload::text AS payload FROM catalog_releases");
    const refs = new Map<string, boolean>();
    const add = (value: unknown, retained: boolean) => {
      for (const sha256 of shas(value)) refs.set(sha256, retained || refs.get(sha256) === true);
    };
    for (const row of authors.rows) add(row.cover, false);
    for (const row of home.rows) add(row.cover, false);
    for (const row of releases.rows) add(row.payload, row.is_active !== true);
    return { complete: true, refs: [...refs.entries()].map(([sha256, retainedRelease]) => ({ sha256, retainedRelease })) };
  } catch {
    return { complete: false, refs: [] };
  }
}
