import { createHash } from "node:crypto";
import type { z } from "zod";
import { adminReply, authorizeAdmin, type AdminGuardDeps } from "./auth.ts";
import { allowedMethods, matchAdminRoute, type AdminRouteSpec } from "./route-specs.ts";
import { AppError, type ErrorCode } from "../kernel/errors.ts";
import { requestHash } from "../kernel/canonical.ts";
import { idempotencyKeySchema } from "../catalog/domain/contracts.ts";
import { ACTOR_HEADER, DEFAULT_ACTOR, IDEMPOTENCY_HEADER, REPLAY_HEADER, actorSchema, errorCodes } from "../catalog/domain/contracts.ts";
import { MEDIA_MAX_BYTES } from "./media-contracts.ts";
import { LIMITS } from "../kernel/limits.ts";
import { REQUEST_ID_HEADER, requestIdFrom, type RequestContext } from "../platform/observability/context.ts";
import type { UnitOfWork } from "../platform/db/uow.ts";
import { scopedPermission, verifyAdminScope, type AdminIdentity } from "./permissions.ts";

export interface AdminEnvelopeSuccess<T> { readonly ok: true; readonly data: T; readonly requestId: string }
export interface AdminEnvelopeFailure {
  readonly ok: false;
  readonly error: { readonly code: ErrorCode; readonly message: string; readonly details?: unknown };
  readonly requestId: string;
}
export type AdminEnvelope<T = unknown> = AdminEnvelopeSuccess<T> | AdminEnvelopeFailure;

export interface AdminHandlerInput {
  readonly params: unknown;
  readonly query: unknown;
  readonly body: unknown;
  readonly context: RequestContext & { readonly actor: string };
  /** Set when the journal encloses the handler, so media SQL and the catalog journal share one commit. */
  readonly participant?: UnitOfWork;
}
export type AdminHandler = (input: AdminHandlerInput) => Promise<{ readonly data: unknown; readonly status?: number }>;

export interface IdempotencyClaim {
  readonly key: string;
  readonly route: string;
  readonly requestSha256: string;
  readonly requestId: string;
  readonly actor: string;
  readonly action: string | null;
}
export interface AdminJournal {
  prepare(claim: IdempotencyClaim): Promise<{ readonly replay?: { readonly status: number; readonly data: unknown } }>;
  finish(claim: IdempotencyClaim, outcome: { readonly status: number; readonly data: unknown }): Promise<void>;
  /** Runs the handler and the journal insert before COMMIT. A throw rolls both back. */
  enclose?(claim: IdempotencyClaim, work: (participant: UnitOfWork) => Promise<{ readonly data: unknown; readonly status?: number }>): Promise<{ readonly data: unknown; readonly status?: number; readonly replay?: boolean }>;
}

export interface DispatchDeps {
  readonly handlers: ReadonlyMap<string, AdminHandler>;
  readonly authorize: (request: Request) => Promise<Response | null>;
  readonly identity?: (request: Request) => AdminIdentity | null;
  readonly journal?: AdminJournal;
  readonly uuid?: () => string;
  readonly mapError?: (error: unknown, requestId: string) => AppError;
}

const denials = { 503: ["unconfigured", "The admin API is not configured."], 429: ["rate_limited", "Too many requests."], 401: ["unauthorized", "Unauthorized."] } as const;

function issues(error: z.ZodError) {
  return error.issues.map((issue) => ({ path: issue.path.map(String).join("."), code: issue.code, message: issue.message }));
}

function envelope(body: AdminEnvelope, status: number, requestId: string, extra: Record<string, string> = {}): Response {
  return adminReply(body, status, { [REQUEST_ID_HEADER]: requestId, ...extra });
}

function fail(error: AppError, requestId: string, extra: Record<string, string> = {}): Response {
  const body: AdminEnvelopeFailure = {
    ok: false,
    error: { code: error.code, message: error.message, ...(error.details === undefined ? {} : { details: error.details }) },
    requestId,
  };
  return envelope(body, errorCodes[error.code], requestId, extra);
}

async function readJson(request: Request, maxBytes: number): Promise<unknown> {
  if (Number(request.headers.get("content-length") ?? 0) > maxBytes) throw new AppError("payload_too_large", "The body is larger than 1 MB.");
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength > maxBytes) throw new AppError("payload_too_large", "The body is larger than 1 MB.");
  if (bytes.byteLength === 0) return undefined;
  try { return JSON.parse(new TextDecoder().decode(bytes)) as unknown; } catch { throw new AppError("invalid", "The body is not valid JSON."); }
}

function dryRun(query: unknown, body: unknown): boolean {
  if (query !== null && typeof query === "object" && (query as { dryRun?: unknown }).dryRun === true) return true;
  if (body !== null && typeof body === "object" && (body as { apply?: unknown }).apply === false) return true;
  if (body !== null && typeof body === "object" && (body as { dryRun?: unknown }).dryRun === true) return true;
  return false;
}

/** Multipart identity: SHA-256 of the file bytes plus the normalized string fields. The boundary is not part of the hash. */
export function multipartHash(bytes: Uint8Array, fields: Readonly<Record<string, string>>): string {
  const hash = createHash("sha256");
  hash.update(bytes);
  hash.update(JSON.stringify(Object.entries(fields).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))));
  return hash.digest("hex");
}

async function readMultipart(request: Request): Promise<{ readonly bytes: Uint8Array; readonly fields: Record<string, string> }> {
  if (Number(request.headers.get("content-length") ?? 0) > MEDIA_MAX_BYTES + LIMITS.mediaMultipartOverhead) throw new AppError("payload_too_large", "File too large: the limit is 4 MB. Compress or resize the image and retry.");
  let form: FormData;
  try { form = await request.formData(); } catch { throw new AppError("invalid", "Expected multipart/form-data."); }
  const file = form.get("file");
  if (!(file instanceof Blob) || file.size === 0) throw new AppError("invalid", "A non-empty file field is required.");
  if (file.size > MEDIA_MAX_BYTES) throw new AppError("payload_too_large", "File too large: the limit is 4 MB. Compress or resize the image and retry.");
  const fields = Object.fromEntries([...form.entries()].filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1] !== ""));
  return { bytes: new Uint8Array(await file.arrayBuffer()), fields };
}

function needsKey(spec: AdminRouteSpec, query: unknown, body: unknown): boolean {
  if (spec.idempotency === "required") return true;
  if (spec.idempotency === "unless-dry-run") return !dryRun(query, body);
  return false;
}

/** Authorize, match, parse, then the handler. Authorization happens before the body is read. */
export async function dispatchAdminRequest(request: Request, deps: DispatchDeps): Promise<Response> {
  const url = new URL(request.url);
  const requestId = requestIdFrom(request.headers.get(REQUEST_ID_HEADER), deps.uuid ?? (() => crypto.randomUUID()));
  const denied = await deps.authorize(request);
  if (denied) return denied;
  const matched = matchAdminRoute(request.method, url.pathname);
  if (!matched) {
    const allow = allowedMethods(url.pathname);
    if (allow.length) return adminReply({ ok: false, error: { code: "invalid", message: "Method not allowed." }, requestId }, 405, { [REQUEST_ID_HEADER]: requestId, Allow: allow.join(", ") });
    return fail(new AppError("not_found", "Unknown admin route."), requestId);
  }
  const spec = matched.spec;
  try {
    if (spec.permission && deps.identity) {
      const identity = deps.identity(request);
      if (!identity) throw new AppError("forbidden", "This credential cannot perform that operation in this environment.");
      verifyAdminScope(identity, scopedPermission(spec.permission, identity.environment), identity.environment);
    }
    const actorHeader = request.headers.get(ACTOR_HEADER) ?? DEFAULT_ACTOR;
    const actor = actorSchema.safeParse(actorHeader);
    if (!actor.success) throw new AppError("invalid", "X-Tower-Actor must match ^[a-z0-9:@._ -]{1,64}$.");
    const params = spec.params.safeParse(matched.params);
    if (!params.success) throw new AppError("invalid", "Invalid path parameter.", issues(params.error));
    const rawQuery = Object.fromEntries([...url.searchParams].filter(([, value]) => value !== ""));
    const query = spec.query.safeParse(rawQuery);
    if (!query.success) throw new AppError("invalid", "Invalid query.", issues(query.error));
    let rawBody: unknown;
    let body: unknown;
    let requestSha = requestHash(rawQuery, null);
    if (spec.body.kind === "none") body = undefined;
    else if (spec.body.kind === "json") {
      rawBody = await readJson(request, spec.body.maxBytes);
      const parsed = spec.body.schema.safeParse(rawBody);
      if (!parsed.success) throw new AppError("invalid", "Invalid body.", issues(parsed.error));
      body = parsed.data;
      requestSha = requestHash(rawQuery, rawBody);
    } else {
      const multipart = await readMultipart(request);
      body = multipart;
      requestSha = multipartHash(multipart.bytes, multipart.fields);
    }
    const route = `${spec.method} ${url.pathname.slice(url.pathname.indexOf(spec.scope === "media" ? "/api/admin/media" : "/api/admin/catalog"))}`;
    let claim: IdempotencyClaim | null = null;
    if (needsKey(spec, query.data, body)) {
      const key = idempotencyKeySchema.safeParse(request.headers.get(IDEMPOTENCY_HEADER));
      if (!key.success) throw new AppError("invalid", "This route requires an Idempotency-Key header (≤ 128 of [A-Za-z0-9._:-]).");
      claim = { key: key.data, route, requestSha256: requestSha, requestId, actor: actor.data, action: spec.action };
      const prepared = await deps.journal?.prepare(claim);
      if (prepared?.replay) {
        return envelope({ ok: true, data: prepared.replay.data, requestId }, prepared.replay.status, requestId, { [REPLAY_HEADER]: "true" });
      }
    }
    const handler = deps.handlers.get(spec.handlerId);
    if (!handler) throw new AppError("internal", `No handler for ${spec.handlerId}.`);
    const input = {
      params: params.data,
      query: query.data,
      body,
      context: { requestId, route: spec.handlerId, startedAt: Date.now(), actor: actor.data },
    };
    const outcome: { readonly data: unknown; readonly status?: number; readonly replay?: boolean } = claim && deps.journal?.enclose
      ? await deps.journal.enclose(claim, (participant) => handler({ ...input, participant }))
      : await handler(input);
    const status = outcome.status ?? 200;
    if (outcome.replay) return envelope({ ok: true, data: outcome.data, requestId }, status, requestId, { [REPLAY_HEADER]: "true" });
    if (claim && !deps.journal?.enclose && status >= 200 && status < 300) await deps.journal?.finish(claim, { status, data: outcome.data });
    return envelope({ ok: true, data: outcome.data, requestId }, status, requestId);
  } catch (error) {
    const mapped = error instanceof AppError ? error : deps.mapError?.(error, requestId) ?? new AppError("internal", "The admin API failed.");
    return fail(mapped, requestId);
  }
}

/** Shared guard as a Response, used by both catch-alls. 429 keeps Retry-After. */
export async function adminAuthorization(request: Request, deps: AdminGuardDeps): Promise<Response | null> {
  const denied = await authorizeAdmin(request, deps);
  if (!denied) return null;
  const code = denied.status === 503 ? "unconfigured" : denied.status === 429 ? "rate_limited" : "unauthorized";
  const message = denials[denied.status][1];
  const requestId = requestIdFrom(request.headers.get(REQUEST_ID_HEADER), () => crypto.randomUUID());
  return fail(new AppError(code, message), requestId, denied.status === 429 ? { "Retry-After": String(denied.retryAfter) } : {});
}
