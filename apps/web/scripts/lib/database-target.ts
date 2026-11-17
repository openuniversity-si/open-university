export class DatabaseToolError extends Error {}

export const targetVariables = {
  container: "APP_DATABASE_URL_CONTAINER_UNPOOLED",
  staging: "APP_DATABASE_URL_STAGING_UNPOOLED",
  prod: "APP_DATABASE_URL_PROD_UNPOOLED",
} as const;

export type DatabaseTarget = keyof typeof targetVariables;

const remoteTargets = ["staging", "prod"] as const satisfies readonly DatabaseTarget[];
const localHosts = ["localhost", "127.0.0.1", "[::1]", "postgres"];
const tlsModes = ["require", "verify-ca", "verify-full"];

export function parseTargetArgs(args: readonly string[], allowDryRun = true): { target: DatabaseTarget; dryRun: boolean } {
  let target: DatabaseTarget | undefined;
  let dryRun = false;
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--target" && target === undefined) {
      const value = args[++i];
      if (value === undefined || !Object.hasOwn(targetVariables, value)) {
        throw new DatabaseToolError("Unknown target. Use container, staging, or prod.");
      }
      target = value as DatabaseTarget;
    } else if (arg === "--dry-run" && allowDryRun && !dryRun) {
      dryRun = true;
    } else {
      throw new DatabaseToolError("Invalid arguments. Use --target <target> and optionally --dry-run.");
    }
  }
  if (target === undefined) throw new DatabaseToolError("An explicit --target is required.");
  return { target, dryRun };
}

export function validateDatabaseUrl(connectionString: string, target: DatabaseTarget): URL {
  let url: URL;
  try { url = new URL(connectionString); } catch { throw new DatabaseToolError("Invalid database URL; value redacted."); }
  if (!(["postgres:", "postgresql:"].includes(url.protocol))) {
    throw new DatabaseToolError("Database URL must use postgres or postgresql.");
  }
  const database = decodeURIComponent(url.pathname.slice(1));
  const local = localHosts.includes(url.hostname);
  if (target === "container") {
    if (!local || !/^tower_test(?:_[a-z0-9]+)?$/.test(database)) {
      throw new DatabaseToolError("Container target requires a local tower_test database.");
    }
  } else {
    if (!database || local || !url.username) {
      throw new DatabaseToolError("Remote targets require a remote host, a role and a database name.");
    }
    if (!tlsModes.includes(url.searchParams.get("sslmode") ?? "")) {
      throw new DatabaseToolError("Remote targets require sslmode=require, verify-ca or verify-full.");
    }
  }
  return url;
}

export function resolveDatabaseTarget(target: DatabaseTarget, env: Readonly<Record<string, string | undefined>> = process.env): string {
  const variable = targetVariables[target];
  const scoped = env.APP_DATABASE_TARGET === target ? env.APP_DATABASE_URL_UNPOOLED : undefined;
  const connectionString = env[variable] ?? scoped ?? (target === "container" ? env.TEST_DATABASE_URL : undefined);
  if (!connectionString) throw new DatabaseToolError(`Missing ${variable} (or APP_DATABASE_URL_UNPOOLED with APP_DATABASE_TARGET=${target}).`);
  const url = validateDatabaseUrl(connectionString, target);
  if (target !== "container") {
    for (const other of remoteTargets) {
      const value = env[targetVariables[other]];
      if (other === target || !value) continue;
      const otherUrl = validateDatabaseUrl(value, other);
      if (url.host === otherUrl.host && url.pathname === otherUrl.pathname) throw new DatabaseToolError("Remote targets must be distinct databases.");
    }
  }
  return connectionString;
}

export function safeDatabaseError(error: unknown): string {
  return error instanceof DatabaseToolError ? error.message : "Database operation failed; driver details redacted. Check credentials, connectivity, and permissions privately.";
}
