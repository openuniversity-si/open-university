import pg from "pg";

const CATALOG_TABLES = "catalog_media, admin_idempotency, r2_pending_deletions, catalog_imports, home_row_items, home_rows, catalog_texts, lesson_videos, lessons, course_editions, courses, authors, content_sources, licenses, slug_redirects";

/** Empties the catalog tables and restarts the id sequences; current tests create their own synthetic rows. */
export async function resetCatalogTables(connectionString: string): Promise<void> {
  const client = new pg.Client({ connectionString });
  await client.connect();
  try {
    // Tiny fixtures: DELETE avoids rewriting every relation/index file on every case (TRUNCATE does).
    // Dependency order is explicit; constraints and triggers stay enabled.
    await client.query(`BEGIN; TRUNCATE catalog_ship_chunks, catalog_ship_batches, catalog_jobs, catalog_redirects, catalog_release_index, catalog_course_projections, catalog_audit, catalog_releases RESTART IDENTITY; ${CATALOG_TABLES.split(", ").map((table) => `DELETE FROM ${table};`).join(" ")}`);
    // Taxonomy is whatever the migrated database held (tower_test.*, copied at clone). Tests insert their own rows;
    // this puts titles and positions back and drops the ones a test added. No id list in code (D-030).
    const snapshot = await client.query<{ present: boolean }>("SELECT to_regclass('tower_test.subject_areas') IS NOT NULL AS present");
    if (!snapshot.rows[0]?.present) throw new Error("tower_test.subject_areas is missing; the integration database was not cloned with its taxonomy snapshot");
    await client.query("UPDATE subject_subareas SET position = position + coalesce((SELECT max(position) FROM subject_subareas), 0), title = '~' || id");
    await client.query("UPDATE subject_subareas s SET area_id = t.area_id, title = t.title, position = t.position FROM tower_test.subject_subareas t WHERE s.id = t.id");
    await client.query("DELETE FROM subject_subareas WHERE NOT EXISTS (SELECT 1 FROM tower_test.subject_subareas t WHERE t.id = subject_subareas.id)");
    await client.query("DELETE FROM subject_areas WHERE NOT EXISTS (SELECT 1 FROM tower_test.subject_areas t WHERE t.id = subject_areas.id)");
    await client.query("UPDATE subject_areas SET position = position + coalesce((SELECT max(position) FROM subject_areas), 0), title = '~' || id");
    await client.query("UPDATE subject_areas a SET title = t.title, position = t.position FROM tower_test.subject_areas t WHERE a.id = t.id");
    await client.query("UPDATE catalog_home SET revision = 1, updated_at = now()");
    await client.query(`SELECT setval(format('%I.%I', schemaname, sequencename)::regclass, start_value, false)
      FROM pg_sequences WHERE schemaname = 'public'
      AND sequencename IN ('author_seq', 'course_seq', 'edition_seq', 'lesson_seq')`);
    await client.query("COMMIT");
  } catch (error) { await client.query("ROLLBACK"); throw error; }
  finally { await client.end(); }
}
