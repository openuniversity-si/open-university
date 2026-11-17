import "server-only";
import { cache } from "react";
import { remember } from "../../platform/freshness/next.ts";
import { CACHE } from "../../kernel/cache.ts";
import { buildWithoutDatabase } from "../../platform/db/database-env.ts";
import { appPool } from "../../platform/db/pool.ts";
import { codeDocument, parseDocument, type ConfigDocument, type ConfigKind } from "../domain/documents.ts";
import { configRepository } from "./repository.ts";

/** Every cached configuration read carries this tag. A write expires it. */
export const CONFIG_TAG = "config";

export function configTag(kind: ConfigKind): string {
  return `${CONFIG_TAG}:${kind}`;
}

async function loadStored(kind: ConfigKind): Promise<unknown> {
  const row = await configRepository(appPool()).read(kind);
  return row === null ? null : row.body;
}

function fromStored(kind: ConfigKind, stored: unknown): ConfigDocument {
  if (stored === null || stored === undefined) return codeDocument(kind);
  return parseDocument(kind, stored);
}

/** The stored revision, or the code when there is no row, no database, or the row is outside the contract. */
export const readServed = cache(async (kind: ConfigKind, load: (kind: ConfigKind) => Promise<unknown> = loadStored): Promise<ConfigDocument> => {
  if (buildWithoutDatabase()) return codeDocument(kind);
  try {
    const stored = await remember(() => load(kind), ["config-served", kind], {
      tags: [CONFIG_TAG, configTag(kind)],
      revalidate: CACHE.untilTagged,
    })();
    return fromStored(kind, stored);
  } catch {
    return codeDocument(kind);
  }
});
