import { AppError } from "../../kernel/errors.ts";
import { currentEnv, type EnvInput } from "../../kernel/env.ts";

const profiles = new Map<string, unknown>();

function source(input?: EnvInput): EnvInput {
  return input ?? currentEnv();
}

function remember<T>(name: string, input: EnvInput | undefined, parse: (env: EnvInput) => T): T {
  if (input) return parse(input);
  const hit = profiles.get(name);
  if (hit !== undefined) return hit as T;
  const value = parse(currentEnv());
  profiles.set(name, value);
  return value;
}

/** Whether the URL this adapter reads is present. Legacy names are ignored. */
export function hasDatabase(input?: EnvInput): boolean {
  return Boolean(source(input).APP_DATABASE_URL?.trim());
}

export function buildWithoutDatabase(input?: EnvInput): boolean {
  const env = source(input);
  return !env.APP_DATABASE_URL && env.NEXT_PHASE === "phase-production-build";
}

export function getDatabaseEnv(input?: EnvInput): Readonly<{ databaseUrl: string; maxPoolSize: number }> {
  return remember("database", input, (env) => {
    const databaseUrl = env.APP_DATABASE_URL?.trim() ?? "";
    if (!/^postgres(?:ql)?:\/\//.test(databaseUrl)) throw new AppError("unconfigured", "APP_DATABASE_URL is required.");
    const raw = env.APP_POOL_MAX?.trim() ?? "5";
    const maxPoolSize = Number(raw);
    if (!/^[1-9]\d*$/.test(raw) || maxPoolSize > 20) throw new AppError("invalid", "APP_POOL_MAX must be an integer from 1 to 20.");
    return { databaseUrl, maxPoolSize };
  });
}
