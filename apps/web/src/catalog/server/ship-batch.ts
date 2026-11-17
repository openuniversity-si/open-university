import type { ShipBatchBody, ShipBatchCommitted, ShipBatchData } from "../domain/ship-batch.ts";
import { batchContentHash } from "../domain/ship-batch.ts";
import type { HandlerContext } from "./http.ts";
import type { Outcome, Tx } from "./mutation.ts";
import { readCourseState } from "./common.ts";
import { publishRelease, scheduleActivation } from "./releases.ts";
import { catalogCourseFacts, evaluateRules } from "../domain/rules/status.ts";
import { duplicateFailures, parseBundles } from "../domain/rules/batch.ts";
import { refKeys, referenceFailures } from "../domain/rules/refs.ts";
import { notWrittenFailures } from "../domain/rules/lifecycle.ts";
import { catalogRefsPort } from "./refs.ts";
import { invalid, preconditionsFailed } from "../../kernel/errors.ts";
import { commitShipBatch, openShipBatch, publishShipCourses, readShipBatchRow, readShipChunks, saveShipChunk, writeBundles } from "./table-io.ts";

export { writeBundles };

function elapsed(start: number): number {
  return Math.max(0, Math.round(performance.now() - start));
}

function asBundles(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === "string") {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed) ? parsed : [];
  }
  return [];
}

interface BatchRow { status: string; draft: boolean; allow_orphan: boolean; note: string | null; chunk_count: number; result: unknown }

async function loadBatch(tx: Tx, hash: string): Promise<BatchRow> {
  const row = await readShipBatchRow(tx, hash);
  if (!row) throw invalid("The ship batch was not opened.");
  const note = row.note;
  return { status: String(row.status), draft: row.draft === true, allow_orphan: row.allow_orphan === true, note: typeof note === "string" ? note : null, chunk_count: Number(row.chunk_count), result: row.result };
}

/**
 * POST /bundles/ship. One batch, one release. Chunks only stage JSON; the completing request
 * validates every bundle, writes with set-based upserts, and commits the release in that same transaction.
 * The same content hash returns the stored result and does not cut another release.
 */
export async function shipBatch(context: HandlerContext<unknown, unknown, ShipBatchBody>): Promise<Outcome<ShipBatchData>> {
  const body = context.body;
  const hash = body.batchHash;
  const allowOrphan = body.allowOrphan !== false;
  const note = body.note ?? null;
  const started = performance.now();
  let committed: ShipBatchCommitted | null = null;
  const outcome = await context.mutate(async (tx) => {
    await tx.acquireLock({ scope: "xact", key: `ship-batch:${hash}` });
    await openShipBatch(tx, hash, body.draft, allowOrphan, note, body.chunks);
    const batch = await loadBatch(tx, hash);
    if (batch.status === "committed") return { data: batch.result as ShipBatchData, noop: true, entity: `ship:${hash.slice(0, 12)}` };
    if (batch.draft !== body.draft || batch.allow_orphan !== allowOrphan || batch.note !== note || batch.chunk_count !== body.chunks) {
      throw invalid("This batch hash was already opened with different options.");
    }
    await saveShipChunk(tx, hash, body.chunk, JSON.stringify(body.bundles));
    const stored = await readShipChunks(tx, hash);
    if (stored.length < body.chunks) {
      await tx.audit({ action: "course.publish.ship", entityKind: "ship", entityId: hash.slice(0, 16), after: { status: "partial", received: stored.length, chunks: body.chunks } });
      const partial: ShipBatchData = { status: "partial", batchHash: hash, received: stored.length, chunks: body.chunks };
      return { data: partial, entity: `ship:${hash.slice(0, 12)}` };
    }
    const validateStarted = performance.now();
    const parsed = parseBundles(stored.flatMap((row) => asBundles(row.bundles)));
    const failures = [...parsed.failures, ...duplicateFailures(parsed.bundles)];
    if (failures.length > 0) throw preconditionsFailed(failures);
    if (batchContentHash(parsed.bundles) !== hash) throw invalid("The batch hash does not match its bundles.");
    const refs = await catalogRefsPort(tx).load(refKeys(parsed.bundles));
    const references = referenceFailures(parsed.bundles, refs);
    if (references.length > 0) throw preconditionsFailed(references);
    const validateMs = elapsed(validateStarted);
    const writeStarted = performance.now();
    await writeBundles(tx, parsed.bundles, refs, context.deps.now().toISOString());
    const ids = parsed.bundles.map((bundle) => bundle.course.id);
    let release: ShipBatchCommitted["release"] = null;
    let releaseMs = 0;
    if (!body.draft) {
      await publishShipCourses(tx, ids);
      const state = await readCourseState(tx, ids);
      const factsByCourse = catalogCourseFacts(state.tables, state.covers);
      const blocked = [...notWrittenFailures(ids, new Set(factsByCourse.keys())), ...ids.flatMap((id) => {
        const facts = factsByCourse.get(id);
        return facts ? evaluateRules("published", facts, { allowOrphan }) : [];
      })];
      if (blocked.length > 0) throw preconditionsFailed(blocked);
      const releaseStarted = performance.now();
      const publication = await publishRelease(tx, { note: note ?? `ship batch ${String(ids.length)}`, actor: context.actor, fresh: new Set(ids), now: context.deps.now() });
      releaseMs = elapsed(releaseStarted);
      scheduleActivation(tx, context.deps, publication.release, publication.release.created);
      release = { number: publication.release.number, sha: publication.release.sha, created: publication.release.created, previous: publication.previous };
    }
    const writeMs = elapsed(writeStarted) - releaseMs;
    committed = {
      status: "committed", batchHash: hash, draft: body.draft, courses: ids, release,
      phases: { validateMs, writeMs, releaseMs, totalMs: elapsed(started) },
    };
    await commitShipBatch(tx, hash, JSON.stringify(committed));
    await tx.audit({
      action: "course.publish.ship", entityKind: "ship", entityId: hash.slice(0, 16),
      after: { draft: body.draft, courses: ids.length, release: release?.number ?? null }, releaseNumber: release?.number ?? null,
    });
    return { status: 201, data: committed, entity: `ship:${hash.slice(0, 12)}` };
  });
  return outcome as Outcome<ShipBatchData>;
}
