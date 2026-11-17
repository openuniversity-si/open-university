import { AppError, stateConflict, unprocessable } from "../../kernel/errors.ts";

/** PostgreSQL errors a race can still raise after the service's own checks, as API errors; anything else is null. */
export function fromDatabaseError(error: unknown, options: { readonly slugConstraints: ReadonlySet<string> }): AppError | null {
  const { code, constraint, detail } = (error ?? {}) as { code?: unknown; constraint?: unknown; detail?: unknown };
  const name = typeof constraint === "string" ? constraint : "";
  if (code === "23505") return options.slugConstraints.has(name) ? new AppError("slug_taken", `Already taken (${name}).`) : stateConflict(`Conflicts with an existing row (${name || "unique"}).`);
  if (code === "23503") return typeof detail === "string" && detail.includes("still referenced") ? new AppError("has_dependents", `Still referenced (${name}).`) : unprocessable(`Unknown reference (${name}).`);
  if (code === "23514") return unprocessable(`Violates ${name || "a check constraint"}.`);
  if (code === "55000") return stateConflict("Releases are immutable; only activation changes.");
  return null;
}
