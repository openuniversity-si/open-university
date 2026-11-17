import type { ErrorCode } from "../../../src/catalog/domain/contracts.ts";

// tower-catalog exit codes (docs/catalog/cli.md): one per failure class, so scripts can branch on them.
export const EXIT = { ok: 0, api: 1, usage: 2, conflict: 3, preconditions: 4, unprocessable: 5, access: 6, network: 7 } as const;
export type ExitCode = (typeof EXIT)[keyof typeof EXIT];

/** A failure the CLI reports and exits with; messages never carry secrets, bodies or preview tokens. */
export class CliError extends Error {
  readonly exitCode: ExitCode;
  constructor(message: string, exitCode: ExitCode) {
    super(message);
    this.name = "CliError";
    this.exitCode = exitCode;
  }
}

/** Bad arguments, a file that does not validate, a refused confirmation: nothing was sent. */
export class UsageError extends CliError {
  constructor(message: string) { super(message, EXIT.usage); this.name = "UsageError"; }
}

/** The API answered an error envelope. */
export class ApiError extends CliError {
  readonly status: number;
  readonly code: ErrorCode | "bad_response";
  readonly details: unknown;
  readonly requestId: string;
  /** The envelope as the API sent it (`--json` prints it). */
  readonly envelope: unknown;
  constructor(status: number, code: ErrorCode | "bad_response", message: string, details: unknown, requestId: string, envelope: unknown) {
    super(`${message} (HTTP ${String(status)} ${code}, requestId ${requestId})`, exitForStatus(status));
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
    this.envelope = envelope;
  }
}

/** Connection refused, DNS, TLS or timeout: the request may or may not have reached the API. */
export class NetworkError extends CliError {
  constructor(message: string) { super(message, EXIT.network); this.name = "NetworkError"; }
}

/** `--dry-run` reached a request that would change something: printed, not sent. */
export class DryRunHalt extends Error {
  constructor() { super("dry run"); this.name = "DryRunHalt"; }
}

export function exitForStatus(status: number): ExitCode {
  if (status === 409) return EXIT.conflict;
  if (status === 412) return EXIT.preconditions;
  if (status === 422) return EXIT.unprocessable;
  if (status === 401 || status === 429 || status === 503) return EXIT.access;
  return EXIT.api;
}
