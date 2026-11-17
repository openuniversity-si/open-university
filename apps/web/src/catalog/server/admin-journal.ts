import "server-only";
import type { AdminJournal, IdempotencyClaim } from "../../admin/http-dispatcher.ts";
import { checkIdempotency, IdempotentReplay, type AdminPool } from "./mutation.ts";
import { withUnitOfWork, type UnitOfWork } from "../../platform/db/uow.ts";

async function writeJournal(client: UnitOfWork, claim: IdempotencyClaim, outcome: { readonly status: number; readonly data: unknown }): Promise<void> {
  if (!claim.action || outcome.status < 200 || outcome.status >= 300) return;
  await client.query(`INSERT INTO catalog_audit (actor, request_id, action, entity_kind, entity_id, before, after, release_number)
    VALUES ($1, $2, $3, 'media', $4, NULL, $5::jsonb, NULL)`, [claim.actor, claim.requestId, claim.action, claim.route, JSON.stringify(outcome.data)]);
  await client.query(`INSERT INTO admin_idempotency (key, route, request_sha256, status, response) VALUES ($1, $2, $3, $4, $5::jsonb) ON CONFLICT (key) DO NOTHING`,
    [claim.key, claim.route, claim.requestSha256, outcome.status, JSON.stringify({ data: outcome.data })]);
}

/**
 * Catalog owns `catalog_audit` and `admin_idempotency`. Media mutations pass the same unit of work
 * into `enclose`, so a rollback drops the media rows and the journal together. The SQL stays in this module.
 */
export function catalogAdminJournal(pool: () => AdminPool): AdminJournal {
  return {
    async prepare(claim) {
      try {
        await checkIdempotency(pool(), { key: claim.key, route: claim.route, requestSha256: claim.requestSha256 });
        return {};
      } catch (error) {
        if (error instanceof IdempotentReplay) return { replay: { status: error.status, data: error.data } };
        throw error;
      }
    },
    async enclose(claim, work) {
      try {
        return await withUnitOfWork(pool(), async (client) => {
          await client.acquireLock({ scope: "xact", key: `idempotency:${claim.key}` });
          await checkIdempotency(client, { key: claim.key, route: claim.route, requestSha256: claim.requestSha256 }, true);
          const outcome = await work(client);
          const status = outcome.status ?? 200;
          await writeJournal(client, claim, { status, data: outcome.data });
          return { data: outcome.data, status };
        });
      } catch (error) {
        if (error instanceof IdempotentReplay) return { data: error.data, status: error.status, replay: true };
        throw error;
      }
    },
    async finish(claim, outcome) {
      await withUnitOfWork(pool(), async (client) => {
        await writeJournal(client, claim, outcome);
      });
    },
  };
}
