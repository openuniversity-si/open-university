import { canonicalJson, sha256Hex } from "../../../src/kernel/canonical.ts";
import { REQUEST_ID_HEADER } from "../../../src/platform/observability/context.ts";
import { ADMIN_ROUTE_SPECS, type AdminRouteSpec } from "../../../src/admin/route-specs.ts";
import {
  ACTOR_HEADER, ADMIN_CATALOG_BASE, errorCodes, IDEMPOTENCY_HEADER, idempotencyKeySchema, REPLAY_HEADER, type AdminSuccess, type ErrorCode,
} from "../../../src/catalog/domain/contracts.ts";
import { ApiError, DryRunHalt, NetworkError, UsageError } from "./errors.ts";
import type { Output } from "./io.ts";
import { redact, redactText, scrub } from "./redact.ts";
import type { ResponseOf } from "./responses.ts";
import { cliRoute, isServerDryRun, type BodyOf, type QueryOf, type RouteKey } from "./routes.ts";
import { secretFor, type Credentials, type Target } from "./target.ts";

/** One HTTP exchange. `admin` requests carry the Bearer (added by the transport, never by the caller). */
export interface WireRequest {
  readonly method: string;
  readonly url: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly body?: string;
  /** Rebuilt on every attempt so a consumed multipart stream is never reused. */
  readonly form?: () => FormData;
  readonly timeoutMs: number;
  readonly admin: boolean;
}
export interface WireResponse { readonly status: number; readonly headers: Headers; readonly text: string }
export type Transport = (request: WireRequest) => Promise<WireResponse>;

/**
 * The production transport: `fetch` with the Bearer taken from the credentials the
 * bash wrapper passed on a file descriptor. Admin calls refuse redirects, so the header never follows one to another
 * host. A failure names the method, path, error class and the cause code and message. It never includes the URL's query,
 * a header, the request body or a secret.
 */
export function fetchTransport(credentials: Credentials, target: Target, fetchImpl: typeof fetch = fetch): Transport {
  return async (request) => {
    const headers = new Headers(request.headers);
    if (request.admin) headers.set("authorization", `Bearer ${secretFor(credentials, target)}`);
    // One deadline for the request and its body. A plain setTimeout keeps the process alive while a request hangs:
    // AbortSignal.timeout's timer does not, so Node used to drain with exit 13 and no error.
    const controller = new AbortController();
    const timer = setTimeout(() => { controller.abort(new TransportTimeout()); }, request.timeoutMs);
    const aborted = new Promise<never>((_, reject) => {
      controller.signal.addEventListener("abort", () => { reject(controller.signal.reason as Error); }, { once: true });
    });
    aborted.catch(() => undefined);
    try {
      const response = await Promise.race([fetchImpl(request.url, {
        method: request.method, headers, ...(request.form ? { body: request.form() } : request.body === undefined ? {} : { body: request.body }),
        redirect: request.admin ? "error" : "manual", signal: controller.signal,
      }), aborted]);
      const text = await Promise.race([response.text(), aborted]);
      return { status: response.status, headers: response.headers, text };
    } catch (error) {
      const timedOut = error instanceof TransportTimeout || controller.signal.reason instanceof TransportTimeout;
      const detail = timedOut ? `timeout after ${String(request.timeoutMs / 1000)} s` : networkDetail(error, request, credentials, target);
      throw new NetworkError(`${request.method} ${new URL(request.url).pathname}: ${detail}`);
    } finally {
      clearTimeout(timer);
    }
  };
}

const CAUSE_CODE = /^[A-Z][A-Z0-9_]{0,40}$/;

/** `TypeError: UND_ERR_SOCKET ECONNRESET other side closed` — code and message of the cause, nothing from the request. */
function networkDetail(error: unknown, request: WireRequest, credentials: Credentials, target: Target): string {
  if (!(error instanceof Error)) return "network error";
  const nested = causeChain(error);
  const coded = nested.length > 0 ? nested : [error];
  const codes = coded.map(causeCode).filter((code, index, all) => code.length > 0 && all.indexOf(code) === index);
  const message = nested.map((cause) => causeMessage(cause.message, request, credentials, target)).find((text) => text.length > 0) ?? "";
  const detail = [...codes, message].filter((part) => part.length > 0).join(" ");
  return detail.length > 0 ? `${error.name}: ${detail}` : error.name;
}

function causeChain(error: Error): Error[] {
  const chain: Error[] = [];
  const seen = new Set<unknown>([error]);
  let current: unknown = error.cause;
  while (current instanceof Error && !seen.has(current) && chain.length < 4) {
    chain.push(current);
    seen.add(current);
    current = current.cause;
  }
  return chain;
}

function causeCode(error: Error): string {
  const code = (error as { code?: unknown }).code;
  return typeof code === "string" && CAUSE_CODE.test(code) ? code : "";
}

function causeMessage(message: string, request: WireRequest, credentials: Credentials, target: Target): string {
  let text = message.replace(/\s+/g, " ").trim();
  text = text.replace(/https?:\/\/\S+/g, "");
  if (request.url) text = text.split(request.url).join("");
  if (request.body) text = text.split(request.body).join("");
  for (const value of Object.values(request.headers)) if (value.length >= 4) text = text.split(value).join("");
  const secret = secretFor(credentials, target);
  text = text.split(`Bearer ${secret}`).join("");
  text = scrub(redactText(text), [credentials.secrets.prod, credentials.secrets.preview]);
  return text.replace(/\s+/g, " ").trim().slice(0, 180);
}

class TransportTimeout extends Error {
  constructor() { super("timeout"); this.name = "TimeoutError"; }
}

/** Idempotency keys by intent (docs/catalog/cli.md): the same command, arguments, files and request give the same key. */
export interface Intent {
  readonly command: string;
  /** Canonical arguments (positionals and options, without output/confirmation flags). */
  readonly args: unknown;
  /** sha256 of every file the command read, by path. */
  readonly files: Readonly<Record<string, string>>;
  /** `--idem-nonce`, else the UTC day: a repeat after a timeout reuses the stored answer; tomorrow's run is a new intent. */
  readonly window: string;
}
export function idempotencyKey(intent: Intent, request: { route: string; params: unknown; query: unknown; body: unknown; state: unknown }): string {
  const hash = sha256Hex(canonicalJson({ ...intent, ...request }));
  return `tc-${intent.command.replace(/[^a-z0-9]+/g, ".")}-${hash.slice(0, 40)}`;
}

export interface CallInput<K extends RouteKey> {
  readonly params?: Readonly<Record<string, string>>;
  readonly query?: QueryOf<K>;
  readonly body?: BodyOf<K>;
  /** What the command read right before the call and is not in the body (e.g. the active release before an activation). */
  readonly state?: unknown;
}
export interface CallResult<T> { readonly envelope: AdminSuccess<T>; readonly data: T; readonly replayed: boolean; readonly status: number }

export interface ClientOptions {
  readonly origin: string;
  readonly target: Target;
  readonly transport: Transport;
  readonly actor: string;
  readonly uuid: () => string;
  readonly sleep: (ms: number) => Promise<void>;
  readonly dryRun: boolean;
  /** Clock for the media retry deadline. Catalog retries keep their own attempt cap. */
  readonly now?: () => number;
  readonly deadlineMs?: number;
  readonly intent: () => Intent;
  /** `--idempotency-key`: used for the first keyed request, `<key>.2`, `<key>.3`… for the next ones. */
  readonly fixedKey: string | undefined;
  readonly out: Output;
}

/** Routes whose change needs a y/N (or --yes) on every target; on prod every change does. */
export function needsConfirmation(key: RouteKey, query: Readonly<Record<string, string>>, target: Target, body?: unknown): boolean {
  if (!cliRoute(key).mutates || isServerDryRun(key, query, body)) return false;
  if (target === "prod") return true;
  return ["POST /courses/:id/publish", "POST /courses/publish-batch", "POST /courses/:id/unpublish", "POST /releases/:n/activate", "POST /texts/approve", "PUT /home"].includes(key) || cliRoute(key).method === "DELETE";
}

const RETRIES = [500, 1500];
/** Retry-After is a minimum, whether seconds or an HTTP date; bounded attempts add exponential jitter. */
export function rateRetryDelay(header: string | null, attempt: number, now = Date.now(), random = Math.random()): number {
  const seconds = header !== null && /^\d+(?:\.\d+)?$/.test(header.trim()) ? Number(header) * 1000 : Date.parse(header ?? "") - now;
  return Math.max(0, Number.isFinite(seconds) ? seconds : 0) + Math.round(500 * 2 ** attempt * (1 + random));
}

export class ApiClient {
  private readonly options: ClientOptions;
  private keyed = 0;
  /** Set by Context.confirm(): until then, a change that needs confirmation is refused here, whatever the command does. */
  confirmed = false;
  /** Set by `media --read-only-api`: any non-GET admin call is refused before the transport. */
  readOnly = false;
  /** Every request the client sent, `METHOD /path` (tests and the route-coverage guardian read it). */
  readonly sent: { key: string; method: string; path: string; idempotencyKey: string | null }[] = [];

  constructor(options: ClientOptions) { this.options = options; }

  get origin(): string { return this.options.origin; }

  async call<K extends RouteKey>(key: K, input: CallInput<K> = {}): Promise<CallResult<ResponseOf<K>>> {
    const route = cliRoute(key);
    const params = input.params ?? {};
    const path = route.path.replace(/:(\w+)/g, (_match, name: string) => {
      const value = params[name];
      if (value === undefined) throw new UsageError(`Missing ${name} for ${key}.`);
      return encodeURIComponent(value);
    });
    const query = Object.fromEntries(Object.entries((input.query ?? {}) as Record<string, string | undefined>).filter((entry): entry is [string, string] => entry[1] !== undefined));
    const queryCheck = route.query.safeParse(query);
    if (!queryCheck.success) throw new UsageError(`Invalid query for ${key}: ${issueList(queryCheck.error.issues)}`);
    if (route.body !== null) {
      const bodyCheck = route.body.safeParse(input.body);
      if (!bodyCheck.success) throw new UsageError(`Invalid request for ${key}: ${issueList(bodyCheck.error.issues)}`);
    }
    const search = new URLSearchParams(query).toString();
    const target = `${path}${search ? `?${search}` : ""}`;
    const serverDryRun = isServerDryRun(key, query, input.body);
    const keyed = route.idempotency === "required" || (route.idempotency === "unless-dry-run" && !serverDryRun);
    const idempotencyKey = keyed ? this.nextKey(key, params, query, input.body, input.state) : null;
    const body = route.body === null || input.body === undefined ? undefined : JSON.stringify(input.body);

    if (route.mutates && !serverDryRun && this.options.dryRun) {
      this.options.out.note(`DRY-RUN: ${route.method} ${ADMIN_CATALOG_BASE}${target}${idempotencyKey ? ` (Idempotency-Key ${idempotencyKey})` : ""}`);
      if (body !== undefined) this.options.out.note(JSON.stringify(redact(input.body), null, 2));
      this.options.out.note("DRY-RUN: not sent; nothing changed.");
      throw new DryRunHalt();
    }
    if (needsConfirmation(key, query, this.options.target, input.body) && !this.confirmed) {
      throw new UsageError(`Refusing ${route.method} ${route.path} on ${this.options.target} without a confirmation (y/N or --yes).`);
    }

    const requestId = this.options.uuid();
    const headers: Record<string, string> = { [REQUEST_ID_HEADER]: requestId, [ACTOR_HEADER]: this.options.actor, accept: "application/json" };
    if (body !== undefined) headers["content-type"] = "application/json";
    if (idempotencyKey) headers[IDEMPOTENCY_HEADER] = idempotencyKey;
    const retryable = route.method === "GET" || route.safe || (route.method === "POST" && idempotencyKey !== null);
    this.sent.push({ key, method: route.method, path: target, idempotencyKey });

    for (let attempt = 0; ; attempt += 1) {
      let response: WireResponse;
      try {
        response = await this.options.transport({ method: route.method, url: `${this.options.origin}${ADMIN_CATALOG_BASE}${target}`, headers, ...(body === undefined ? {} : { body }), timeoutMs: route.timeoutMs, admin: true });
      } catch (error) {
        if (error instanceof NetworkError && retryable && attempt < RETRIES.length) { await this.options.sleep(RETRIES[attempt] ?? 0); continue; }
        if (error instanceof NetworkError) throw new NetworkError(`${error.message} (requestId ${requestId}${idempotencyKey ? `; re-run the same command to reuse Idempotency-Key ${idempotencyKey}` : ""})`);
        throw error;
      }
      if (response.status === 429 && attempt < 4) { await this.options.sleep(rateRetryDelay(response.headers.get("retry-after"), attempt)); continue; }
      const envelope = parseEnvelope(response, requestId);
      if (!envelope.ok) {
        throw new ApiError(response.status, envelope.error.code, envelope.error.message, envelope.error.details, envelope.requestId, envelope);
      }
      const replayed = response.headers.get(REPLAY_HEADER) === "true";
      if (replayed) this.options.out.note(`Replayed the stored answer of Idempotency-Key ${idempotencyKey ?? "?"}: the API did nothing new.`);
      return { envelope: envelope as AdminSuccess<ResponseOf<K>>, data: envelope.data as ResponseOf<K>, replayed, status: response.status };
    }
  }

  /** A public page or /api/health on the same site, without the Bearer (post-publish checks). */
  async publicGet(path: string): Promise<WireResponse> {
    const response = await this.options.transport({ method: "GET", url: `${this.options.origin}${path}`, headers: { accept: "*/*" }, timeoutMs: 30_000, admin: false });
    return response;
  }

  private nextKey(route: string, params: unknown, query: unknown, body: unknown, state: unknown): string {
    this.keyed += 1;
    const fixed = this.options.fixedKey;
    if (fixed !== undefined) return this.keyed === 1 ? fixed : `${fixed}.${String(this.keyed)}`;
    return idempotencyKey(this.options.intent(), { route, params, query, body: body ?? null, state: state ?? null });
  }

  /** Media (and any other registry route) through the same envelope, confirmation and retry as `call`. */
  async adminCall<T>(input: AdminCall, decode: (raw: unknown) => T): Promise<AdminCallResult<T>> {
    const route = adminSpec(input.routeId);
    const query = Object.fromEntries(Object.entries(input.query).filter((entry): entry is [string, string | number | boolean] => entry[1] !== undefined).map(([name, value]) => [name, String(value)]));
    const queryCheck = route.query.safeParse(query);
    if (!queryCheck.success) throw new UsageError(`Invalid query for ${route.id}: ${issueList(queryCheck.error.issues)}`);
    if (route.body.kind === "json") {
      const bodyCheck = route.body.schema.safeParse(input.payload.kind === "json" ? input.payload.value : undefined);
      if (!bodyCheck.success) throw new UsageError(`Invalid request for ${route.id}: ${issueList(bodyCheck.error.issues)}`);
    }
    if (input.payload.kind === "multipart" && route.body.kind !== "multipart") throw new UsageError(`${route.id} does not accept a file.`);
    const path = route.path.replace(/:(\w+)/g, (_match, name: string) => {
      const value = input.params[name];
      if (value === undefined) throw new UsageError(`Missing ${name} for ${route.id}.`);
      return encodeURIComponent(value);
    });
    const search = new URLSearchParams(query).toString();
    const target = `${path === "/" ? "" : path}${search ? `?${search}` : ""}`;
    const serverDry = mediaServerDry(route, input.payload);
    const keyed = route.idempotency === "required" || (route.idempotency === "unless-dry-run" && !serverDry);
    const idempotencyKey = keyed ? (input.idempotencyKey ?? this.nextKey(route.id, input.params, query, input.payload.kind === "json" ? input.payload.value : input.payload, input.payload)) : null;
    const json = route.body.kind === "json" ? JSON.stringify(input.payload.kind === "json" ? input.payload.value : {}) : undefined;
    const base = route.scope === "media" ? "/api/admin/media" : ADMIN_CATALOG_BASE;
    if (route.action !== null && !serverDry && this.options.dryRun && input.stage !== true) {
      this.options.out.note(`DRY-RUN: ${route.method} ${base}${target}${idempotencyKey ? ` (Idempotency-Key ${idempotencyKey})` : ""}`);
      this.options.out.note("DRY-RUN: not sent; nothing changed.");
      throw new DryRunHalt();
    }
    if (this.readOnly && route.method !== "GET") throw new UsageError(`--read-only-api refuses ${route.method} ${route.path}.`);
    if (route.action !== null && !serverDry && this.options.target === "prod" && !this.confirmed) {
      throw new UsageError(`Refusing ${route.method} ${route.path} on prod without a confirmation (y/N or --yes).`);
    }
    const requestId = this.options.uuid();
    const headers: Record<string, string> = { [REQUEST_ID_HEADER]: requestId, [ACTOR_HEADER]: this.options.actor, accept: "application/json" };
    if (json !== undefined) headers["content-type"] = "application/json";
    if (idempotencyKey) headers[IDEMPOTENCY_HEADER] = idempotencyKey;
    const multipart = input.payload.kind === "multipart" ? input.payload : null;
    const form = multipart ? () => mediaForm(multipart) : undefined;
    const retryable = route.method === "GET" || route.safe || idempotencyKey !== null;
    this.sent.push({ key: route.id, method: route.method, path: target || "/", idempotencyKey });
    const now = this.options.now ?? Date.now;
    const deadline = now() + (this.options.deadlineMs ?? 120_000);
    for (let attempt = 0; ; attempt += 1) {
      let response: WireResponse;
      try {
        response = await this.options.transport({ method: route.method, url: `${this.options.origin}${base}${target}`, headers, ...(form ? { form } : json === undefined ? {} : { body: json }), timeoutMs: route.timeoutMs, admin: true });
      } catch (error) {
        if (error instanceof NetworkError && retryable && attempt < 4 && now() < deadline) { await this.options.sleep(RETRIES[Math.min(attempt, RETRIES.length - 1)] ?? 0); continue; }
        if (error instanceof NetworkError) throw new NetworkError(`${error.message} (requestId ${requestId}${idempotencyKey ? `; re-run the same command to reuse Idempotency-Key ${idempotencyKey}` : ""})`);
        throw error;
      }
      if (response.status === 429 && attempt < 4) {
        const delay = rateRetryDelay(response.headers.get("retry-after"), attempt, now());
        if (now() + delay > deadline) throw new ApiError(429, "rate_limited", "Retry deadline elapsed.", undefined, requestId, null);
        await this.options.sleep(delay);
        continue;
      }
      const envelope = parseEnvelope(response, requestId);
      if (!envelope.ok) throw new ApiError(response.status, envelope.error.code, envelope.error.message, envelope.error.details, envelope.requestId, envelope);
      let data: T;
      try { data = decode(envelope.data); } catch (error) { throw new ApiError(response.status, "bad_response", error instanceof Error ? error.message : "Undecodable media response.", undefined, envelope.requestId, envelope); }
      return { data, requestId: envelope.requestId, replayed: response.headers.get(REPLAY_HEADER) === "true" };
    }
  }
}

export interface PreparedMedia {
  readonly bytes: Uint8Array;
  readonly sha256: string;
  readonly extension: "jpg" | "png" | "webp" | "avif";
  readonly contentType: string;
  readonly width: number;
  readonly height: number;
}
export type AdminPayload = { readonly kind: "none" } | { readonly kind: "json"; readonly value: unknown } | { readonly kind: "multipart"; readonly file: PreparedMedia; readonly fields: Readonly<Record<string, string>> };
export interface AdminCall {
  readonly routeId: string;
  /**
   * Cover bytes staged before a server dry run. `ship` uploads them even under `--dry-run`: the catalog change is
   * `POST /batches/apply` with `dryRun: true`, and that transaction attaches the objects by sha.
   */
  readonly stage?: boolean;
  readonly params: Readonly<Record<string, string>>;
  readonly query: Readonly<Record<string, string | number | boolean | undefined>>;
  readonly payload: AdminPayload;
  readonly idempotencyKey?: string;
}
export interface AdminCallResult<T> { readonly data: T; readonly requestId: string; readonly replayed: boolean }
export interface AdminClient {
  call<T>(input: AdminCall, decode: (raw: unknown) => T): Promise<AdminCallResult<T>>;
}

export function validateFixedKey(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  if (!idempotencyKeySchema.safeParse(value).success || value.length > 120) throw new UsageError("--idempotency-key must be ≤ 120 of [A-Za-z0-9._:-].");
  return value;
}

type Envelope = AdminSuccess | { ok: false; error: { code: ErrorCode; message: string; details?: unknown }; requestId: string };
function parseEnvelope(response: WireResponse, requestId: string): Envelope {
  let parsed: unknown;
  try { parsed = JSON.parse(response.text); } catch { parsed = null; }
  const value = parsed as { ok?: unknown; data?: unknown; error?: { code?: unknown; message?: unknown; details?: unknown }; requestId?: unknown } | null;
  if (value !== null && typeof value === "object" && typeof value.requestId === "string") {
    if (value.ok === true && "data" in value) return value as AdminSuccess;
    if (value.ok === false && typeof value.error?.code === "string" && Object.hasOwn(errorCodes, value.error.code) && typeof value.error.message === "string") return value as Envelope;
  }
  throw new ApiError(response.status, "bad_response", `The API answered HTTP ${String(response.status)} without the admin envelope (wrong URL, a protected preview, or a deployment without /api/admin/catalog)`, undefined, requestId, null);
}

export function issueList(issues: readonly { path: readonly PropertyKey[]; message: string }[]): string {
  return issues.map((issue) => `${issue.path.map(String).join(".") || "(root)"}: ${issue.message}`).join("; ");
}

function adminSpec(routeId: string): AdminRouteSpec {
  const route = ADMIN_ROUTE_SPECS.find((entry) => entry.id === routeId);
  if (!route) throw new UsageError(`Unknown admin route ${routeId}.`);
  return route;
}

function mediaServerDry(route: AdminRouteSpec, payload: AdminPayload): boolean {
  if (route.idempotency !== "unless-dry-run" || payload.kind !== "json" || payload.value === null || typeof payload.value !== "object") return false;
  const value = payload.value as { apply?: unknown; dryRun?: unknown };
  return value.apply === false || value.dryRun === true;
}

function mediaForm(payload: Extract<AdminPayload, { kind: "multipart" }>): FormData {
  const form = new FormData();
  form.set("file", new Blob([Buffer.from(payload.file.bytes)], { type: payload.file.contentType }), `file.${payload.file.extension}`);
  for (const [name, value] of Object.entries(payload.fields)) form.set(name, value);
  return form;
}
