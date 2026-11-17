import "server-only";
import { z } from "zod";
import { adminReply, authorizeAdmin, type AdminGuardDeps } from "../../admin/auth.ts";
import { ACTOR_HEADER, DEFAULT_ACTOR, actorSchema, MAX_BODY_BYTES } from "../../catalog/domain/contracts.ts";
import { AppError, invalid, notFound } from "../../kernel/errors.ts";
import { LIMITS } from "../../kernel/limits.ts";
import { REQUEST_ID_HEADER, requestIdFrom } from "../../platform/observability/context.ts";
import { codeDocument, matchConfigRequest, parseDocument, type ConfigKind } from "../domain/documents.ts";
import type { ConfigDocuments, ConfigRevision } from "../ports/documents.ts";

/** The catalog guard plus the configuration port. The route file only delegates here. */
export interface ConfigAdminDeps extends AdminGuardDeps {
  readonly documents: ConfigDocuments;
  readonly invalidate?: (kind: ConfigKind) => void;
}

const noteSchema = z.string().max(LIMITS.text).nullable().optional();
const writeSchema = z.object({
  expectedRevision: z.number().int().nonnegative(),
  document: z.unknown(),
  note: noteSchema,
}).strict();
const rollbackSchema = z.object({
  revision: z.number().int().nonnegative(),
  expectedRevision: z.number().int().nonnegative(),
  note: noteSchema,
}).strict();

const denials = {
  503: ["unconfigured", "The admin API is not configured."],
  429: ["rate_limited", "Too many requests."],
  401: ["unauthorized", "Unauthorized."],
} as const;

function fail(error: AppError, requestId: string, headers: Record<string, string> = {}): Response {
  return adminReply({
    ok: false,
    error: { code: error.code, message: error.message, ...(error.details === undefined ? {} : { details: error.details }) },
    requestId,
  }, error.status, { [REQUEST_ID_HEADER]: requestId, ...headers });
}

function ok(data: unknown, requestId: string, status = 200): Response {
  return adminReply({ ok: true, data, requestId }, status, { [REQUEST_ID_HEADER]: requestId });
}

async function readJson(request: Request): Promise<unknown> {
  if (Number(request.headers.get("content-length") ?? 0) > MAX_BODY_BYTES) throw new AppError("payload_too_large", "The body is larger than 1 MB.");
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength > MAX_BODY_BYTES) throw new AppError("payload_too_large", "The body is larger than 1 MB.");
  if (bytes.byteLength === 0) return undefined;
  try { return JSON.parse(new TextDecoder().decode(bytes)) as unknown; }
  catch { throw invalid("The body is not valid JSON."); }
}

function actorOf(request: Request, secret: string | undefined): string {
  const header = request.headers.get(ACTOR_HEADER) ?? DEFAULT_ACTOR;
  const actor = actorSchema.safeParse(header);
  if (!actor.success || (secret !== undefined && header.includes(secret))) throw invalid("X-Tower-Actor must match ^[a-z0-9:@._ -]{1,64}$.");
  return actor.data;
}

function view(row: ConfigRevision) {
  return { kind: row.kind, revision: row.revision, document: row.body, actor: row.actor, note: row.note, at: row.at };
}

async function effective(deps: ConfigAdminDeps, kind: ConfigKind) {
  const stored = await deps.documents.read(kind);
  if (stored === null) return { kind, revision: 0, source: "code" as const, document: codeDocument(kind) };
  return { ...view(stored), source: "database" as const };
}

/** GET the served value, PUT a new revision, GET history, or POST a rollback. */
export async function handleConfigAdmin(request: Request, deps: ConfigAdminDeps): Promise<Response> {
  const requestId = requestIdFrom(request.headers.get(REQUEST_ID_HEADER), () => crypto.randomUUID());
  const denied = await authorizeAdmin(request, deps);
  if (denied) {
    const headers: Record<string, string> = {};
    if (denied.status === 429) headers["Retry-After"] = String(denied.retryAfter);
    const [code, message] = denials[denied.status];
    return fail(new AppError(code, message), requestId, headers);
  }
  const url = new URL(request.url);
  const matched = matchConfigRequest(request.method, url.pathname);
  if (matched === null) return fail(notFound("Route"), requestId);
  if (matched.action === null) return fail(new AppError("invalid", "Method not allowed."), requestId);
  try {
    const actor = actorOf(request, deps.secret);
    const { kind } = matched;
    if (matched.action === "read") return ok(await effective(deps, kind), requestId);
    if (matched.action === "history") {
      const revisions = await deps.documents.history(kind);
      return ok({ kind, revisions: revisions.map(view) }, requestId);
    }
    const raw = await readJson(request);
    if (matched.action === "write") {
      const parsed = writeSchema.safeParse(raw);
      if (!parsed.success) throw invalid("Invalid body.");
      const stored = await deps.documents.commit({
        kind,
        expectedRevision: parsed.data.expectedRevision,
        body: parseDocument(kind, parsed.data.document),
        actor,
        note: parsed.data.note ?? null,
      });
      deps.invalidate?.(kind);
      return ok(view(stored), requestId);
    }
    const parsed = rollbackSchema.safeParse(raw);
    if (!parsed.success) throw invalid("Invalid body.");
    const source = parsed.data.revision === 0
      ? codeDocument(kind)
      : (await deps.documents.history(kind)).find((row) => row.revision === parsed.data.revision)?.body;
    if (source === undefined) throw notFound("Revision");
    const stored = await deps.documents.commit({
      kind,
      expectedRevision: parsed.data.expectedRevision,
      body: source,
      actor,
      note: parsed.data.note ?? null,
    });
    deps.invalidate?.(kind);
    return ok(view(stored), requestId);
  } catch (error) {
    if (error instanceof AppError) return fail(error, requestId);
    return fail(new AppError("internal", "The configuration API failed."), requestId);
  }
}
