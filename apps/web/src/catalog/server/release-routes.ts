import type { Outcome } from "./mutation.ts";
import { lockReleases } from "./mutation.ts";
import { notFound } from "../../kernel/errors.ts";
import type { HandlerContext } from "./http.ts";
import { iso } from "./common.ts";
import { activateNumber, assertServable, compileNext, diffReleases, publishRelease, readActive, readRelease, releaseCounts, scheduleActivation, type Publication } from "./releases.ts";

export async function listReleases(context: HandlerContext<unknown, unknown, unknown>): Promise<Outcome> {
  const { rows } = await context.db.query("SELECT number, payload_sha256, counts, note, created_by, created_at, is_active, activated_at FROM catalog_releases ORDER BY number DESC");
  return {
    data: {
      releases: rows.map((row) => ({
        number: Number(row.number), sha: String(row.payload_sha256), counts: row.counts, note: String(row.note), createdBy: String(row.created_by),
        createdAt: iso(row.created_at), isActive: row.is_active === true, activatedAt: iso(row.activated_at),
      })),
    },
  };
}

export async function getRelease(context: HandlerContext<{ n: number }, unknown, unknown>): Promise<Outcome> {
  return { data: { release: await readRelease(context.db, context.params.n) } };
}

/** `?dryRun=true`: compile and validate only ({valid, errors, diff}); otherwise create release MAX+1 and activate it. */
export async function createRelease(context: HandlerContext<unknown, { dryRun?: boolean }, { note: string } | undefined>): Promise<Outcome> {
  if (context.query.dryRun === true) {
    const active = await readActive(context.db);
    try {
      const next = await compileNext(context.db, active, new Set(), context.deps.now());
      return { data: { valid: true, errors: [], unchanged: next.unchanged, diff: diffReleases(active?.payload ?? null, next.payload), counts: releaseCounts(next.payload) } };
    } catch (error) {
      const details = (error as { details?: { errors?: string[] } }).details;
      if (details?.errors) return { data: { valid: false, errors: details.errors, diff: null } };
      throw error;
    }
  }
  const note = context.body?.note ?? "Release";
  let publication: Publication | null = null;
  const outcome = await context.mutate(async (tx) => {
    publication = await publishRelease(tx, { note, actor: context.actor, fresh: new Set(), now: context.deps.now() });
    const noop = !publication.release.created;
    scheduleActivation(tx, context.deps, publication.release, publication.release.created);
    return { status: noop ? 200 : 201, data: { release: publication.release, diff: publication.diff, ...(noop ? { noop: true } : {}) }, noop, entity: `release:${String(publication.release.number)}` };
  });
  return outcome;
}

/** Rollback or roll-forward to release N: one UPDATE pair in the transaction, revalidation after the commit. */
export async function activateRelease(context: HandlerContext<{ n: number }, unknown, { note: string }>): Promise<Outcome> {
  const number = context.params.n;
  const outcome = await context.mutate(async (tx) => {
    await lockReleases(tx);
    const { rows } = await tx.query("SELECT number, payload, payload_sha256, is_active FROM catalog_releases WHERE number = $1", [number]);
    const row = rows[0];
    if (!row) throw notFound(`Release ${String(number)}`);
    const release = { number, sha: String(row.payload_sha256) };
    if (row.is_active === true) return { data: { release, noop: true }, noop: true, entity: `release:${String(number)}` };
    assertServable(row.payload);
    const previous = await readActive(tx);
    await activateNumber(tx, number);
    await tx.audit({ action: "release.activate", entityKind: "release", entityId: String(number), before: { active: previous?.number ?? null }, after: { active: number, sha: release.sha, note: context.body.note }, releaseNumber: number });
    scheduleActivation(tx, context.deps, release);
    return { data: { release, previous: previous?.number ?? null }, entity: `release:${String(number)}` };
  });
  return outcome;
}
