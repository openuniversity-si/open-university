// Redaction for everything tower-catalog prints: no field of the API carries a secret, but the redactor exists and is
// tested so a future field, a pasted body or an error cannot leak one (docs/catalog/cli.md, "Secrets").
const SENSITIVE_KEY = /authorization|secret|token|password|bypass|cookie/i;
const TOKEN_PARAM = /([?&;\s]token=)[^&\s"']+/gi;
const BEARER = /(bearer\s+)[^\s"']+/gi;
export const REDACTED = "[redacted]";

/** A copy of `value` with sensitive keys and `token=`/`Bearer` values replaced. */
export function redact(value: unknown): unknown {
  if (typeof value === "string") return redactText(value);
  if (Array.isArray(value)) return value.map(redact);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, SENSITIVE_KEY.test(key) ? REDACTED : redact(item)]));
  }
  return value;
}

export function redactText(text: string): string {
  return text.replace(TOKEN_PARAM, `$1${REDACTED}`).replace(BEARER, `$1${REDACTED}`);
}

/** Replaces every occurrence of the known secret values (the admin secrets) in `text`. */
export function scrub(text: string, secrets: readonly string[]): string {
  let out = text;
  for (const secret of secrets) if (secret.length >= 4) out = out.split(secret).join(REDACTED);
  return out;
}
