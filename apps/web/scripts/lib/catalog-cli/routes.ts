import type { z } from "zod";
import { cliProjection } from "../../../src/admin/route-specs.ts";

/**
 * Projection of the pure admin registry (`src/admin/route-specs.ts`). The CLI does not keep a second table and does not
 * import handlers, the dispatcher or the database. `tower-catalog.test.ts` still compares this projection with the
 * catalog routes field by field.
 */
export interface CliRoute {
  readonly method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  readonly path: string;
  readonly query: z.ZodType;
  readonly body: z.ZodType | null;
  readonly idempotency: "required" | "none" | "unless-dry-run";
  /** The API audits it (route.action !== null). */
  readonly mutates: boolean;
  /** A read-only POST. The client repeats it after a network error without an Idempotency-Key. */
  readonly safe: boolean;
  /** Request timeout: 30 s, or 120 s for the routes that compile and activate a release. */
  readonly timeoutMs: number;
}

export const CLI_ROUTES = cliProjection() as { readonly [K in RouteKey]: CliRoute };

export type RouteKey =
  | "GET /courses"
  | "POST /courses"
  | "GET /courses/:id"
  | "PATCH /courses/:id"
  | "DELETE /courses/:id"
  | "POST /courses/:id/status"
  | "POST /courses/:id/publish"
  | "POST /courses/publish-batch"
  | "POST /courses/classify"
  | "POST /courses/:id/unpublish"
  | "GET /courses/:id/editions"
  | "POST /courses/:id/editions"
  | "PUT /courses/:id/editions/order"
  | "PATCH /editions/:id"
  | "DELETE /editions/:id"
  | "PUT /editions/:id/lessons/order"
  | "POST /courses/:id/lessons"
  | "PUT /courses/:id/lessons/order"
  | "PUT /lessons/slugs"
  | "PATCH /lessons/:id"
  | "DELETE /lessons/:id"
  | "GET /authors"
  | "POST /authors"
  | "PATCH /authors/:id"
  | "DELETE /authors/:id"
  | "GET /texts"
  | "PUT /texts"
  | "POST /texts/approve"
  | "POST /texts/revoke"
  | "GET /home"
  | "PUT /home"
  | "GET /areas"
  | "POST /areas"
  | "PATCH /areas/:id"
  | "POST /areas/:id/move"
  | "GET /subareas"
  | "POST /subareas"
  | "GET /licenses"
  | "POST /licenses"
  | "GET /sources"
  | "POST /sources"
  | "PATCH /sources/:id"
  | "POST /imports"
  | "POST /imports/:id/draft"
  | "GET /releases"
  | "GET /releases/:n"
  | "POST /releases"
  | "POST /releases/:n/activate"
  | "GET /redirects"
  | "POST /redirects"
  | "DELETE /redirects"
  | "POST /preview-token"
  | "GET /audit"
  | "GET /tables"
  | "POST /media/references"
  | "GET /doctor"
  | "POST /batches/apply"
  | "POST /bundles/validate"
  | "POST /bundles/diff"
  | "POST /bundles/apply"
  | "POST /bundles/ship"
  | "POST /bundles/export"
  | "POST /jobs/claim"
  | "POST /jobs/:id/renew"
  | "POST /jobs/:id/advance"
  | "POST /jobs/:id/complete"
  | "POST /lifecycle/inventory"
  | "POST /lifecycle/gc"
  | "POST /lifecycle/preview-reset";
export const ROUTE_KEYS = Object.keys(CLI_ROUTES) as RouteKey[];

/** The projection is one table, so a missing key is a programming error rather than an optional field. */
export function cliRoute(key: string): CliRoute {
  const route = (CLI_ROUTES as Readonly<Record<string, CliRoute | undefined>>)[key];
  if (!route) throw new Error(`Unknown admin route ${key}.`);
  return route;
}

/** Bodies stay checked by the registry schema at the client; the projection is not a per-key tuple. */
export type BodyOf<K extends RouteKey> = K extends string ? unknown : never;
/** Query strings as sent (the schemas parse strings into booleans and numbers). */
export type QueryOf<K extends RouteKey> = K extends string ? Record<string, string | undefined> : never;

/**
 * Whether a request changes nothing even though its route is a mutation: `POST /releases?dryRun=true`, a
 * `PUT /lessons/slugs` body with `dryRun: true` and the destructive routes without `confirm=true` answer a report.
 * `--dry-run` sends these; it prints everything else.
 */
export function isServerDryRun(key: RouteKey, query: Readonly<Record<string, string>>, body?: unknown): boolean {
  if (key === "POST /releases" || key === "PATCH /lessons/:id") return query.dryRun === "true";
  if (key === "PUT /lessons/slugs" || key === "POST /batches/apply") return (body as { dryRun?: unknown } | undefined)?.dryRun === true;
  if (cliRoute(key).method === "DELETE") return query.confirm !== "true";
  return false;
}
