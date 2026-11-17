import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { AUTH_COOKIE_PREFIX, SESSION_COOKIE_NAMES } from "../identity/domain/settings.ts";
import { PREVIEW_COOKIE } from "../catalog/server/preview-token.ts";
import { AUTH_RETURN_UI_KEY, BRAND_ID, PENDING_COMPLETION_KEY, PREVIEW_COOKIE_NAME } from "./brand-ids.ts";

// Guardian (2026-10-11, Daniel): what the browser shows the visitor (cookie names, storage keys) carries the product name, Open University,
// not "tower". One constant (brand-ids.ts) names them all; this fails if a name goes back to "tower" or is hard-coded elsewhere.
describe("user-visible browser names", () => {
  it("are derived from one brand id and never say tower", () => {
    expect(BRAND_ID).toBe("open-university");
    const names = [AUTH_COOKIE_PREFIX, ...SESSION_COOKIE_NAMES, PREVIEW_COOKIE, PREVIEW_COOKIE_NAME, PENDING_COMPLETION_KEY, AUTH_RETURN_UI_KEY];
    for (const name of names) { expect(name.startsWith("__Secure-") ? name.slice(9) : name).toMatch(/^open-university[.:-]?/); expect(name.toLowerCase()).not.toContain("tower"); }
    expect(SESSION_COOKIE_NAMES).toEqual(["open-university.session_token", "__Secure-open-university.session_token"]);
  });

  it("is a valid cookie-name token (RFC 6265), prefixes included", () => {
    for (const name of SESSION_COOKIE_NAMES) expect(name).toMatch(/^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/);
    expect(`__Secure-${BRAND_ID}.session_data`).toMatch(/^__Secure-[\w.-]+$/);
  });

  it("is hard-coded nowhere else in the source", () => {
    const files: string[] = [];
    // Generated CSS custom-property names include tower-auth-* and are not cookie names.
    const tokenNames = join("src", "ui", "tokens", "names.ts");
    const walk = (dir: string) => { for (const entry of readdirSync(dir)) { const path = join(dir, entry); if (statSync(path).isDirectory()) walk(path); else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry) && entry !== "brand-ids.ts" && path !== tokenNames) files.push(path); } };
    walk("src");
    for (const file of files) expect(readFileSync(file, "utf8"), file).not.toMatch(/["'`](?:__Secure-)?(?:open-university|tower)[.:-](?:session|pending|auth|preview)/);
  });
});
