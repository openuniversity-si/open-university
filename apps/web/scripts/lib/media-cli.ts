import { parseArgs } from "node:util";
import { z } from "zod";
import { transformSchema } from "../../src/media/domain/types.ts";
import type { MediaPool } from "../../src/media/server/repository.ts";
import { createDatabaseClient, queryDatabase, type DatabaseClient } from "./database-client.ts";
import { resolveDatabaseTarget, type DatabaseTarget, targetVariables } from "./database-target.ts";
import { StorageError } from "./r2.ts";

export class MediaToolError extends Error {}
export function mediaArgs(extra: Record<string, { type: "string" | "boolean" }> = {}) {
  const { values } = parseArgs({ options: { course: { type: "string" }, lesson: { type: "string" }, kind: { type: "string" }, variant: { type: "string", default: "default" }, target: { type: "string" }, ...extra } });
  const target = values.target;
  if (typeof target !== "string" || !Object.hasOwn(targetVariables, target)) throw new MediaToolError("Use an explicit --target container|staging|prod.");
  return { values: values as Record<string, string | boolean | undefined>, target: target as DatabaseTarget };
}
export async function mediaConnection(target: DatabaseTarget, readOnly = false): Promise<DatabaseClient> {
  const db = createDatabaseClient(resolveDatabaseTarget(target), readOnly);
  db.on("error", () => { /* Query failure is reported without leaking driver connection details. */ });
  await db.connect(); return db;
}
/**
 * A connected CLI client as a pool of one for the media writes (`swapMedia`…): `connect()` waits until the previous holder
 * released it, so two transactions never interleave on the single connection.
 */
export function poolOfOne(client: DatabaseClient): MediaPool {
  const query = (sql: string, values?: unknown[]) => queryDatabase(client, sql, values);
  let tail = Promise.resolve();
  return {
    query,
    connect() {
      const previous = tail;
      let release = () => { /* replaced below */ };
      tail = new Promise<void>((resolve) => { release = resolve; });
      return previous.then(() => ({ query, release: () => { release(); } }));
    },
  };
}
export function mediaRequired(name: string) {
  const value = process.env[name];
  if (!value) throw new MediaToolError(`${name} is required.`);
  return value;
}
export function revalidationConfig(target: DatabaseTarget) {
  const url = mediaRequired(`TOWER_MEDIA_REVALIDATE_URL_${target.toUpperCase().replaceAll("-", "_")}`);
  const parsed = new URL(url);
  if (parsed.pathname !== "/api/media/revalidate" || parsed.search || parsed.hash || parsed.username || parsed.password || (target === "container" ? !["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname) : parsed.protocol !== "https:")) throw new MediaToolError("Use the target deployment's /api/media/revalidate URL.");
  return { url, secret: mediaRequired("TOWER_MEDIA_REVALIDATE_SECRET") };
}
export async function revalidateMedia(config: { url: string; secret: string }, courseId?: string, change?: { owner: "course" | "lesson"; kind: string; variant?: string }) {
  const response = await fetch(config.url, { method: "POST", redirect: "error", headers: { Authorization: `Bearer ${config.secret}`, "Content-Type": "application/json" }, body: JSON.stringify(courseId ? { courseId, ...change } : {}), signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new MediaToolError("Media saved, but revalidation failed. Retry POST /api/media/revalidate before closing the gate.");
}
export function mediaDescriptor(values: Record<string, string | boolean | undefined>, defaultAlt: string) {
  return {
    alt: z.string().trim().min(1).max(500).parse(values.alt ?? defaultAlt),
    designStatus: z.enum(["approved", "draft", "legacy"]).parse(values["design-status"] ?? "approved"),
    transform: transformSchema.parse(typeof values.transform === "string" ? JSON.parse(values.transform) as unknown : null),
  };
}
export function mediaFailure(error: unknown) {
  console.error(error instanceof MediaToolError || error instanceof StorageError ? error.message : "Media operation failed; credentials and driver details redacted.");
  process.exitCode = 1;
}
