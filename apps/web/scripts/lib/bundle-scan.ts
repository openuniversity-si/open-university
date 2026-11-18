/**
 * Pure helpers for bundle:check (§10.4, §11.1, ADR-11).
 */

/** §10.4: the app's own initial JS per page route (framework runtime excluded), gzip. */
export const INITIAL_JS_BUDGET_BYTES = 150 * 1024;
/** The Home's own initial JS, gzip: 21.2 KB measured on 10/10/2026 (zod left the shell) + 5%. */
export const HOME_INITIAL_JS_BUDGET_BYTES = Math.round(21.2 * 1024 * 1.05);

/** Secret env var names (§11.1 plus legacy names a host may still define). Must never reach client code. */
export const SECRET_ENV_NAMES = [
  "AUTH_SECRET",
  "AUTH_GOOGLE_SECRET",
  "DATABASE_URL",
  "DATABASE_URL_UNPOOLED",
  "APP_DATABASE_URL",
  "APP_DATABASE_URL_UNPOOLED",
  "POSTGRES_URL",
  "POSTGRES_PASSWORD",
  "PGPASSWORD",
  "MUX_SIGNING_PRIVATE_KEY",
  "MUX_TOKEN_ID",
  "MUX_TOKEN_SECRET",
  "FIGMA_TOKEN",
  "TOWER_ADMIN_MEDIA_SECRET",
  "TOWER_ADMIN_SECRET_PROD",
  "TOWER_ADMIN_SECRET_PREVIEW",
  "TOWER_MEDIA_REVALIDATE_SECRET",
  "R2_SECRET_ACCESS_KEY_RW",
  "R2_SECRET_ACCESS_KEY_RO",
  "AWS_SECRET_ACCESS_KEY",
  "AWS_SESSION_TOKEN",
] as const;

export const SECRET_PATTERNS: readonly { readonly name: string; readonly pattern: RegExp }[] = [
  { name: "PEM private key", pattern: /-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----/ },
  { name: "Postgres URL with credentials", pattern: /postgres(?:ql)?:\/\/[^\s:@/"'`]+:[^\s@/"'`]+@/ },
  { name: "GitHub token", pattern: /\bgh[pousr]_[A-Za-z0-9]{36,}\b/ },
  { name: "Google OAuth client secret", pattern: /\bGOCSPX-[A-Za-z0-9_-]{20,}/ },
  { name: "AWS access key id", pattern: /\bAKIA[0-9A-Z]{16}\b/ },
];

const MIN_SECRET_VALUE_LENGTH = 8;

/**
 * Returns what leaked, by name only: never echoes the secret value.
 * `env` lets the check also look for the actual values present at build time.
 */
export function findSecretLeaks(content: string, env: Readonly<Record<string, string | undefined>>): string[] {
  const findings: string[] = [];
  for (const name of SECRET_ENV_NAMES) {
    if (new RegExp(`\\b${name}\\b`).test(content)) findings.push(`env var name ${name}`);
    const value = env[name];
    if (value !== undefined && value.length >= MIN_SECRET_VALUE_LENGTH && content.includes(value)) {
      findings.push(`value of ${name}`);
    }
  }
  for (const { name, pattern } of SECRET_PATTERNS) {
    if (pattern.test(content)) findings.push(name);
  }
  return findings;
}

/**
 * Same-origin script URLs that a modern browser loads for a server-rendered
 * HTML document (`noModule` polyfills are skipped by module-capable browsers).
 */
export function extractScriptPaths(html: string): string[] {
  const paths = new Set<string>();
  for (const match of html.matchAll(/<script\b([^>]*)>/g)) {
    const attributes = match[1] ?? "";
    if (/\bnomodule\b/i.test(attributes)) continue;
    const src = /\bsrc="([^"]+)"/.exec(attributes)?.[1];
    if (src?.startsWith("/_next/static/") === true) paths.add(src.split("?")[0] ?? src);
  }
  return [...paths];
}

/** Next's App Router runtime chunks (build-manifest `rootMainFiles`), as URL paths. */
export function frameworkScriptPaths(buildManifest: { readonly rootMainFiles?: readonly string[] }): Set<string> {
  return new Set((buildManifest.rootMainFiles ?? []).map((file) => `/_next/${file}`));
}
