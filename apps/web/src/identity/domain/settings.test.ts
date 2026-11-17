import { describe, expect, it } from "vitest";
import { PRODUCTION_ORIGIN } from "../../site/domain/origin.ts";
import { hasGoogleCredentials } from "../server/config.ts";
import { hasAuthStorage, resolveAuthBaseURL } from "./settings.ts";

type Env = Readonly<Record<string, string | undefined>>;

function hosted(env: Env, origin: string): string {
  return resolveAuthBaseURL(env.AUTH_URL, origin);
}

const injected = "https://auth.example.invalid";

describe("explicit AUTH_* configuration", () => {
  it("uses the injected production origin when AUTH_URL is absent", () => {
    expect(hosted({}, injected)).toBe(injected);
    expect(hosted({}, PRODUCTION_ORIGIN)).toBe(PRODUCTION_ORIGIN);
  });
  it("uses AUTH_URL ahead of the injected origin", () => {
    expect(hosted({ AUTH_URL: "http://localhost:3100" }, injected)).toBe("http://localhost:3100");
    expect(hosted({ AUTH_URL: "https://auth.example.invalid" }, PRODUCTION_ORIGIN)).toBe("https://auth.example.invalid");
  });
  it("ignores deployment labels: a preview deployment still logs in on the production origin", () => {
    expect(hosted({ SITE_ENV: "preview" }, PRODUCTION_ORIGIN)).toBe(PRODUCTION_ORIGIN);
  });
  it("defaults to the canonical production login host", () => {
    expect(hosted({}, PRODUCTION_ORIGIN)).toBe(PRODUCTION_ORIGIN);
  });
  it.each(["not-a-url", "http://www.thetower.si", "https://user:secret@example.invalid", "https://openuniversity.si/api/auth", "https://openuniversity.si?x=1", "https://openuniversity.si#x", "javascript:alert(1)"])("rejects unsafe AUTH_URL %s", (AUTH_URL) => { // pragma: allowlist secret
    expect(() => hosted({ AUTH_URL }, injected)).toThrow("value redacted");
  });
  it("rejects an injected origin that is not an HTTPS origin", () => {
    expect(() => hosted({}, "http://auth.example.invalid")).toThrow("value redacted");
  });
  it("keeps Google unavailable when either credential is absent", () => {
    expect(hasGoogleCredentials({})).toBe(false);
    expect(hasGoogleCredentials({ AUTH_GOOGLE_ID: "test-client" })).toBe(false);
    expect(hasGoogleCredentials({ AUTH_GOOGLE_SECRET: "test-secret" })).toBe(false);
    expect(hasGoogleCredentials({ AUTH_GOOGLE_ID: " ", AUTH_GOOGLE_SECRET: "test-secret" })).toBe(false);
    expect(hasGoogleCredentials({ AUTH_GOOGLE_ID: "test-client", AUTH_GOOGLE_SECRET: "test-secret" })).toBe(true);
  });
  it("requires explicit signing and DB configuration, ignoring legacy variable names", () => {
    expect(hasAuthStorage({ DATABASE_URL: "postgres://unused", BETTER_AUTH_SECRET: "unused" }, false)).toBe(false);
    expect(hasAuthStorage({ AUTH_SECRET: "test-secret" }, false)).toBe(false);
    expect(hasAuthStorage({ BETTER_AUTH_SECRET: "unused" }, true)).toBe(false);
    expect(hasAuthStorage({}, true)).toBe(false);
    expect(hasAuthStorage({ AUTH_SECRET: "test-secret" }, true)).toBe(true);
  });
});
