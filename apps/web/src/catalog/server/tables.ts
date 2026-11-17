import { readCatalogTables } from "./table-io.ts";
import type { Outcome } from "./mutation.ts";
import type { HandlerContext } from "./http.ts";

/**
 * The normalized catalog tables (tables.ts, the current API export format) and the active release they
 * were read with, in one REPEATABLE READ snapshot: what `tower-catalog snapshot` writes. Read-only, so not audited.
 */
export async function exportTables(context: HandlerContext<unknown, unknown, unknown>): Promise<Outcome> {
  const client = await context.deps.pool().connect();
  let done = false;
  try {
    await client.query("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY");
    const tables = await readCatalogTables(client);
    const { rows } = await client.query("SELECT number, payload_sha256 FROM catalog_releases WHERE is_active");
    await client.query("COMMIT");
    done = true;
    const active = rows[0];
    return { data: { activeRelease: active ? { number: Number(active.number), sha: String(active.payload_sha256) } : null, tables } };
  } finally {
    if (!done) await client.query("ROLLBACK").catch(() => undefined);
    client.release(!done);
  }
}
