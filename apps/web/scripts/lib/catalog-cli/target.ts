import { UsageError } from "./errors.ts";

export const TARGETS = ["preview", "staging", "prod"] as const;
export type Target = (typeof TARGETS)[number];
/** The admin-media.env variable holding each target's site URL (no new secret: the same file as tower-media). */
export const TARGET_URL_VARIABLES: Readonly<Record<Target, string>> = {
  preview: "TOWER_MEDIA_URL_PREVIEW",
  staging: "TOWER_MEDIA_URL_STAGING",
  prod: "TOWER_MEDIA_URL_PROD",
};

/**
 * Hosts tower-catalog may send the admin secret to: the production domain (exactly openuniversity.si) and an AWS Lambda function URL
 * (`<id>.lambda-url.<region>.on.aws`, a staging or preview function). thetower.si is NOT allowed: it belongs to The Tower (a redirect to Open University today, its own site later) and must never
 * receive Open University's admin secret. Anything else (the legacy `a-torre` project, a typo, a non-HTTPS URL) is refused. `tooling/tower-media` delegates
 * to this command, so the rule lives only here.
 */
export const ALLOWED_HOSTS: readonly RegExp[] = [/^openuniversity\.si$/, /^[a-z0-9]+\.lambda-url\.[a-z0-9-]+\.on\.aws$/];

/** The environments sharing `target`'s R2 bucket whose databases a byte delete must consult (prod ↔ preview; staging both). */
export function peerTargets(target: Target): Target[] {
  return target === "staging" ? ["preview", "prod"] : [target === "prod" ? "preview" : "prod"];
}

export function parseTarget(value: string | undefined): Target {
  if (value === undefined) throw new UsageError("--target preview|staging|prod is required (there is no default).");
  if (!(TARGETS as readonly string[]).includes(value)) throw new UsageError(`Unknown --target ${value}; use preview, staging or prod.`);
  return value as Target;
}

/** The site origin of a target, validated against ALLOWED_HOSTS. Messages name the variable, never its value. */
export function targetOrigin(target: Target, env: Readonly<Record<string, string | undefined>>): string {
  const variable = TARGET_URL_VARIABLES[target];
  const raw = env[variable];
  if (!raw) throw new UsageError(`${variable} is not set in admin-media.env; --target ${target} has no URL.`);
  let url: URL;
  try { url = new URL(raw); } catch { throw new UsageError(`${variable} is not a URL.`); }
  if (url.protocol !== "https:") throw new UsageError(`${variable} must be an https:// URL.`);
  if (url.username || url.password || url.search || url.hash || (url.pathname !== "/" && url.pathname !== "")) throw new UsageError(`${variable} must be a bare origin (https://host).`);
  if (!ALLOWED_HOSTS.some((pattern) => pattern.test(url.hostname))) throw new UsageError(`${variable} points to a host outside openuniversity.si and AWS Lambda function URLs; refused.`);
  return url.origin;
}

/** One admin key per deployment environment. Staging is a preview deployment and uses the preview key. */
export interface Credentials { readonly secrets: Readonly<Record<"prod" | "preview", string>> }

export function secretFor(credentials: Credentials, target: Target): string {
  return credentials.secrets[target === "prod" ? "prod" : "preview"];
}

/**
 * The secret file descriptor the bash wrapper writes (`secret.prod=…` and `secret.preview=…` lines; any other line is
 * ignored): no key sits in argv, the environment or a file. A wrapper installed before per-target keys sends one
 * `secret=…` line, which serves every target like the TOWER_ADMIN_MEDIA_SECRET fallback. Messages name the variable
 * that is missing, never a value.
 */
export function parseCredentials(text: string): Credentials {
  const values = new Map<string, string>();
  for (const line of text.split("\n")) {
    const separator = line.indexOf("=");
    if (separator > 0) values.set(line.slice(0, separator), line.slice(separator + 1));
  }
  const shared = values.get("secret") ?? "";
  const prod = values.get("secret.prod") ?? shared;
  const preview = values.get("secret.preview") ?? shared;
  if (!prod && !preview) throw new UsageError("TOWER_ADMIN_SECRET_PROD and TOWER_ADMIN_SECRET_PREVIEW are not set in admin-media.env (nor the fallback TOWER_ADMIN_MEDIA_SECRET).");
  if (!prod) throw new UsageError("TOWER_ADMIN_SECRET_PROD is not set in admin-media.env.");
  if (!preview) throw new UsageError("TOWER_ADMIN_SECRET_PREVIEW is not set in admin-media.env.");
  return { secrets: { prod, preview } };
}
