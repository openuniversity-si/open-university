import type { CoverOwner } from "../../kernel/cover-kinds.ts";
import type { UnitOfWork } from "../../platform/db/uow.ts";

export interface MediaOwnerLock {
  readonly owner: CoverOwner;
  readonly ownerId: string;
}

/**
 * Shared maintenance, then owner keys ordered by the integer Postgres will lock.
 * Hash 0 is remapped to 1 so it cannot collide with maintenance `(742020, 0)`.
 * Call this before row locks. Exclusive mode is the global prune.
 */
export async function lockMediaOwners(tx: UnitOfWork, owners: readonly MediaOwnerLock[], mode: "shared" | "exclusive" = "shared"): Promise<void> {
  await tx.acquireLock({ scope: "media-maintenance", mode });
  if (owners.length === 0) return;
  await tx.query(
    `SELECT pg_advisory_xact_lock(742020, key) FROM (
      SELECT CASE WHEN hashtext(label) = 0 THEN 1 ELSE hashtext(label) END AS key
      FROM unnest($1::text[]) AS label
      GROUP BY 1
      ORDER BY 1
    ) ordered`,
    [owners.map((item) => `${item.owner}:${item.ownerId}`)],
  );
}
