export const errorCodes = {
  invalid: 400,
  unauthorized: 401,
  forbidden: 403,
  not_found: 404,
  revision_conflict: 409,
  state_conflict: 409,
  slug_taken: 409,
  has_dependents: 409,
  preconditions_failed: 412,
  payload_too_large: 413,
  unsupported_media: 415,
  idempotency_mismatch: 422,
  unprocessable: 422,
  rate_limited: 429,
  internal: 500,
  upstream_failed: 502,
  unconfigured: 503,
} as const;
export type ErrorCode = keyof typeof errorCodes;

export interface PreconditionFailure { readonly rule: string; readonly entity: string; readonly message: string }

/** A failure the API answers with its code (contracts.ts); messages never carry secrets, SQL or driver detail. */
export class AppError extends Error {
  readonly code: ErrorCode;
  readonly details: unknown;
  constructor(code: ErrorCode, message: string, details?: unknown) {
    super(message);
    this.name = "AppError";
    this.code = code;
    this.details = details;
  }
  get status(): number { return errorCodes[this.code]; }
}

export const notFound = (what: string) => new AppError("not_found", `${what} not found.`);
export const invalid = (message: string, details?: unknown) => new AppError("invalid", message, details);
export const stateConflict = (message: string, details?: unknown) => new AppError("state_conflict", message, details);
export const unprocessable = (message: string, details?: unknown) => new AppError("unprocessable", message, details);
export const revisionConflict = (currentRevision: number) => new AppError("revision_conflict", `Revision changed: the current revision is ${String(currentRevision)}.`, { currentRevision });
export const preconditionsFailed = (failed: readonly PreconditionFailure[]) => new AppError("preconditions_failed", `${String(failed.length)} precondition(s) failed.`, { failed });

/** Optimistic concurrency: the row's revision must be the one the client saw. */
export function assertRevision(current: number, expected: number): void {
  if (current !== expected) throw revisionConflict(current);
}

/** Secret-free summary of an unexpected error: its class and SQLSTATE/errno code only (as the media API does). */
export function errorSummary(error: unknown): string {
  const name = error instanceof Error ? error.name : "Error";
  const code = typeof (error as { code?: unknown } | null)?.code === "string" ? (error as { code: string }).code : "";
  return `${name}${code ? ` ${code}` : ""}`;
}

