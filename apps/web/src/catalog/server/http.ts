import { REQUEST_ID_HEADER, requestIdFrom } from "../../platform/observability/context.ts";
import type { LogField } from "../../platform/observability/logger.ts";
import type { z } from "zod";
import { adminReply, authorizeAdmin, type AdminGuardDeps } from "../../admin/auth.ts";
import type { MediaInvalidation } from "../../media/domain/tags.ts";
import type { Queryable } from "../../platform/db/uow.ts";
import type { MediaObjectStore } from "../../media/ports/storage.ts";
import { requestHash } from "../../kernel/canonical.ts";
import {
  ACTOR_HEADER, ADMIN_CATALOG_BASE, actorSchema, DEFAULT_ACTOR, errorCodes, IDEMPOTENCY_HEADER, idempotencyKeySchema, MAX_BODY_BYTES,
  REPLAY_HEADER, type AdminFailure, type AdminSuccess, type ErrorCode,
} from "../domain/contracts.ts";
import { AppError, errorSummary, invalid } from "../../kernel/errors.ts";
import { databaseError } from "./errors.ts";
import { checkIdempotency, IdempotentReplay, runMutation, type AdminPool, type Idempotency, type Outcome, type Tx } from "./mutation.ts";
import type { OEmbed } from "../../playback/ports/oembed.ts";
import { ADMIN_ROUTE_SPECS } from "../../admin/route-specs.ts";
import { scopedPermission, verifyAdminScope, type AdminIdentity } from "../../admin/permissions.ts";
import type { AdminEnvironment } from "../../admin/ports/jobs.ts";

/** Everything the admin catalog API touches outside its own code; src/catalog/server/deps.ts wires the real ones. */
export interface AdminCatalogDeps extends AdminGuardDeps {
  readonly pool: () => AdminPool;
  /** Expires the catalog tag and the static Home; called once, after the commit of an activation. */
  readonly invalidateCatalog: (courseIds?: readonly string[]) => void;
  readonly invalidateMedia: (plan: MediaInvalidation) => void;
  readonly oembed: OEmbed;
  /** `lesson_videos.checked_by` for a fresh oEmbed check. deps.ts passes `OEMBED_CHECKER`. */
  readonly oembedChecker: string;
  readonly store: () => MediaObjectStore;
  readonly now: () => Date;
  readonly uuid: () => string;
  /** When set, mutable routes require this credential's environment and scopes before the body is read. */
  readonly adminIdentity?: AdminIdentity;
  /** The deployment's environment (the host adapter); the admin key acts there only. Unset is preview. */
  readonly environment?: AdminEnvironment;
  /** One JSON line per call (CATALOG_ADMIN, CATALOG_RELEASE_ACTIVATED); never bodies or secrets. */
  readonly log: (entry: { readonly event: Uppercase<string>; readonly requestId?: string } & Readonly<Record<string, LogField>>) => void;
  /** Served editorial transitions. Absent keeps the code map, including for unit tests. */
  readonly readStatusTransitions?: () => Promise<Readonly<Record<string, readonly string[]>>>;
}

export interface HandlerContext<P, Q, B> {
  readonly params: P;
  readonly query: Q;
  readonly body: B;
  readonly deps: AdminCatalogDeps;
  readonly requestId: string;
  readonly actor: string;
  /** Reads outside a transaction. */
  readonly db: Queryable;
  /** The one transaction of a mutation (db.ts runMutation), with this request's idempotency key when it has one. */
  mutate(work: (tx: Tx) => Promise<Outcome>): Promise<Outcome>;
}

export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export interface RouteSpec<P, Q, B> {
  readonly method: Method;
  /** Under /api/admin/catalog, with `:param` segments. */
  readonly path: string;
  /** The mutation's name in logs and audit (`course.create`); null for a read. */
  readonly action: string | null;
  readonly idempotency: "required" | "none" | "unless-dry-run";
  readonly params: z.ZodType<P>;
  readonly query: z.ZodType<Q>;
  readonly body: z.ZodType<B> | null;
  readonly handler: (context: HandlerContext<P, Q, B>) => Promise<Outcome>;
}
export interface AdminRoute {
  readonly key: string;
  readonly method: Method;
  readonly path: string;
  readonly action: string | null;
  readonly idempotency: "required" | "none" | "unless-dry-run";
  /** The contracts.ts schemas the route parses: tower-catalog's route table must name the same objects (P5). */
  readonly query: z.ZodType;
  readonly body: z.ZodType | null;
  run(request: Request, params: Readonly<Record<string, string>>, deps: AdminCatalogDeps): Promise<Response>;
}

const denials = { 503: ["unconfigured", "The admin API is not configured."], 429: ["rate_limited", "Too many requests."], 401: ["unauthorized", "Unauthorized."] } as const;

/** Zod issues without the offending values: path, code and message only. */
function issues(error: z.ZodError) {
  return error.issues.map((issue) => ({ path: issue.path.map(String).join("."), code: issue.code, message: issue.message }));
}

async function readJson(request: Request): Promise<unknown> {
  if (Number(request.headers.get("content-length") ?? 0) > MAX_BODY_BYTES) throw new AppError("payload_too_large", "The body is larger than 1 MB.");
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength > MAX_BODY_BYTES) throw new AppError("payload_too_large", "The body is larger than 1 MB.");
  if (bytes.byteLength === 0) return undefined;
  try { return JSON.parse(new TextDecoder().decode(bytes)) as unknown; } catch { throw invalid("The body is not valid JSON."); }
}

function failure(error: unknown, deps: AdminCatalogDeps): AppError {
  if (error instanceof AppError) return error;
  const mapped = databaseError(error);
  if (mapped) return mapped;
  const summary = errorSummary(error);
  deps.log({ event: "CATALOG_ADMIN_ERROR", error: summary });
  return new AppError("upstream_failed", `The catalog database or storage failed (${summary}).`);
}

export function defineRoute<P, Q, B>(spec: RouteSpec<P, Q, B>): AdminRoute {
  const key = `${spec.method} ${spec.path}`;
  return {
    key, method: spec.method, path: spec.path, action: spec.action, idempotency: spec.idempotency, query: spec.query, body: spec.body,
    async run(request, rawParams, deps) {
      const started = Date.now();
      const requestId = requestIdFrom(request.headers.get(REQUEST_ID_HEADER), deps.uuid);
      const headers: Record<string, string> = { [REQUEST_ID_HEADER]: requestId };
      const fail = (error: AppError) => adminReply({ ok: false, error: { code: error.code, message: error.message, ...(error.details === undefined ? {} : { details: error.details }) }, requestId } satisfies AdminFailure, errorCodes[error.code], headers);
      const denied = await authorizeAdmin(request, deps);
      if (denied) {
        if (denied.status === 429) headers["Retry-After"] = String(denied.retryAfter);
        const [code, message] = denials[denied.status];
        return fail(new AppError(code satisfies ErrorCode, message));
      }
      let entity = spec.path;
      const log = (status: number, extra: Record<string, LogField> = {}) => {
        if (spec.action) deps.log({ event: "CATALOG_ADMIN", action: spec.action, entity, requestId, status, ms: Date.now() - started, ...extra });
      };
      try {
        const actorHeader = request.headers.get(ACTOR_HEADER) ?? DEFAULT_ACTOR;
        const actor = actorSchema.safeParse(actorHeader);
        if (!actor.success || (deps.secret !== undefined && actorHeader.includes(deps.secret))) throw invalid("X-Tower-Actor must match ^[a-z0-9:@._ -]{1,64}$.");
        const permission = ADMIN_ROUTE_SPECS.find((entry) => entry.method === spec.method && entry.path === spec.path)?.permission ?? null;
        if (permission && deps.adminIdentity) verifyAdminScope(deps.adminIdentity, scopedPermission(permission, deps.adminIdentity.environment), deps.adminIdentity.environment);
        const params = spec.params.safeParse(rawParams);
        if (!params.success) throw invalid("Invalid path parameter.", issues(params.error));
        const url = new URL(request.url);
        const rawQuery = Object.fromEntries(url.searchParams);
        const query = spec.query.safeParse(rawQuery);
        if (!query.success) throw invalid("Invalid query.", issues(query.error));
        const rawBody = spec.body ? await readJson(request) : undefined;
        const body = spec.body ? spec.body.safeParse(rawBody) : { success: true as const, data: undefined as B };
        if (!body.success) throw invalid("Invalid body.", issues(body.error));
        const dryRun = (query.data as { dryRun?: boolean } | undefined)?.dryRun === true;
        let idempotency: Idempotency | null = null;
        if (spec.idempotency === "required" || (spec.idempotency === "unless-dry-run" && !dryRun)) {
          const key = idempotencyKeySchema.safeParse(request.headers.get(IDEMPOTENCY_HEADER));
          if (!key.success) throw invalid("This route requires an Idempotency-Key header (≤ 128 of [A-Za-z0-9._:-]).");
          idempotency = { key: key.data, route: `${spec.method} ${url.pathname.slice(url.pathname.indexOf(ADMIN_CATALOG_BASE))}`, requestSha256: requestHash(rawQuery, rawBody) };
          await checkIdempotency(deps.pool(), idempotency);
        }
        const meta = { requestId, actor: actor.data };
        const outcome = await spec.handler({
          params: params.data, query: query.data, body: body.data, deps, requestId, actor: actor.data, db: deps.pool(),
          mutate: (work) => runMutation(deps.pool(), meta, idempotency, work),
        });
        entity = outcome.entity ?? entity;
        const status = outcome.status ?? 200;
        log(status, outcome.noop ? { noop: true } : {});
        return adminReply({ ok: true, data: outcome.data, requestId } satisfies AdminSuccess, status, headers);
      } catch (error) {
        if (error instanceof IdempotentReplay) {
          log(error.status, { replay: true });
          return adminReply({ ok: true, data: error.data, requestId } satisfies AdminSuccess, error.status, { ...headers, [REPLAY_HEADER]: "true" });
        }
        const mapped = failure(error, deps);
        log(errorCodes[mapped.code]);
        return fail(mapped);
      }
    },
  };
}
