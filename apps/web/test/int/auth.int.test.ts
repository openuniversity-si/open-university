import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { getCookies } from "better-auth/cookies";
import { createAuthOptions, createTowerAuth, type TowerAuth } from "../../src/identity/server/config.ts";
import { createGoogleSignInRequest } from "../../src/identity/client/return-to.ts";
import { SESSION_CACHE_SECONDS, SESSION_LIFETIME_SECONDS } from "../../src/identity/domain/settings.ts";
import { createDatabaseSession } from "../../e2e/fixtures/session.ts";
import { runMigrations } from "../../scripts/lib/migrations.ts";
import { validateDatabaseUrl } from "../../scripts/lib/database-target.ts";

vi.mock("server-only", () => ({}));

describe("Google-only Better Auth on real PostgreSQL", () => {
  const baseURL = "https://openuniversity.si";
  const secret = randomBytes(32).toString("hex");
  const env = { AUTH_URL: baseURL, AUTH_SECRET: secret, AUTH_GOOGLE_ID: "test-client.apps.googleusercontent.com", AUTH_GOOGLE_SECRET: randomBytes(32).toString("hex") };
  let pool: pg.Pool;
  let auth: TowerAuth;
  let requestNumber = 0;

  function request(path: string, body?: object, cookie?: string, ip = `192.0.2.${String(++requestNumber)}`) {
    return new Request(`${baseURL}/api/auth${path}`, {
      method: body ? "POST" : "GET",
      headers: { origin: baseURL, "content-type": "application/json", "x-forwarded-for": ip, ...(cookie ? { cookie } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
  }

  beforeAll(async () => {
    const connectionString = process.env.TEST_DATABASE_URL;
    if (!connectionString) throw new Error("TEST_DATABASE_URL is required; no auth database mocks.");
    validateDatabaseUrl(connectionString, "container");
    await runMigrations(connectionString, false);
    pool = new pg.Pool({ connectionString });
    // Reset only this suite's buckets so it can also run independently of the F02 reset suite.
    await pool.query("DELETE FROM rate_limit WHERE key = ANY($1::text[])", [["198.51.100.1|/sign-in/social", "198.51.100.2|/sign-in/social", "198.51.100.3|/sign-in/social"]]);
    auth = createTowerAuth(pool, env);
  });

  afterAll(async () => { await pool.end(); });

  it("registers only Google, no password or magic-link plugin, with explicit AUTH_* mapping", async () => {
    const options = createAuthOptions(pool, env);
    const context = await auth.$context;
    expect(context.socialProviders.map((provider) => provider.id)).toEqual(["google"]);
    expect(options.secret).toBe(env.AUTH_SECRET);
    expect(options.baseURL).toBe(env.AUTH_URL);
    expect(options.emailAndPassword?.enabled).toBe(false);
    expect(options.plugins?.map((plugin) => plugin.id)).toEqual(["next-cookies"]);
    expect(context.socialProviders[0]?.options).toMatchObject({ clientId: env.AUTH_GOOGLE_ID, clientSecret: env.AUTH_GOOGLE_SECRET, scope: ["openid", "email", "profile"], accessType: "online", disableIdTokenSignIn: true });
  });

  it.each(["github", "facebook", "apple"])("rejects provider %s", async (provider) => {
    const response = await auth.handler(request("/sign-in/social", { provider, callbackURL: "/" }));
    expect(response.status).toBe(400);
  });

  it.each(["/sign-in/email", "/sign-up/email", "/sign-in/magic-link"])("does not provide a usable %s endpoint", async (path) => {
    const response = await auth.handler(request(path, { email: "viewer@example.invalid", password: "synthetic-password" }));
    expect([400, 404]).toContain(response.status);
  });

  it("starts code/PKCE/state OAuth with only basic scopes and the exact Google callback", async () => {
    const response = await auth.handler(request("/sign-in/social", createGoogleSignInRequest("/c/genesis/lecture-4", 3134)));
    expect(response.status).toBe(200);
    const result = await response.json() as { url: string };
    const url = new URL(result.url);
    expect(url.origin).toBe("https://accounts.google.com");
    expect(url.searchParams.get("redirect_uri")).toBe(`${baseURL}/api/auth/callback/google`);
    expect(url.searchParams.get("response_type")).toBe("code");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("state")).toBeTruthy();
    expect(url.searchParams.get("code_challenge")).toBeTruthy();
    expect(url.searchParams.get("scope")?.split(" ").sort()).toEqual(["email", "openid", "profile"]);
    expect(url.searchParams.get("access_type")).toBe("online");
  });

  it("rejects extra scopes and authorization overrides", async () => {
    for (const additional of [{ scopes: ["https://www.googleapis.com/auth/drive"] }, { additionalParams: { access_type: "offline" } }]) {
      expect((await auth.handler(request("/sign-in/social", { ...createGoogleSignInRequest("/"), ...additional }))).status).toBe(400);
    }
  });

  it("stays available for anonymous and existing sessions without Google credentials", async () => {
    const withoutGoogle = createTowerAuth(pool, { AUTH_URL: baseURL, AUTH_SECRET: secret });
    expect((await withoutGoogle.$context).socialProviders).toHaveLength(0);
    expect(await withoutGoogle.api.getSession({ headers: new Headers() })).toBeNull();
    const fixture = await createDatabaseSession({ pool, baseURL, secret });
    try {
      expect((await withoutGoogle.api.getSession({ headers: new Headers({ cookie: fixture.cookieHeader }) }))?.user.id).toBe(fixture.userId);
      expect((await withoutGoogle.handler(request("/sign-in/social", createGoogleSignInRequest("/")))).status).toBe(404);
    } finally { await fixture.cleanup(); }
  });

  it("accepts an injected signed session, rejects tampering, and deletes it on sign-out", async () => {
    const fixture = await createDatabaseSession({ pool, baseURL, secret, name: "Independent Viewer" });
    try {
      const headers = new Headers({ cookie: fixture.cookieHeader });
      const session = await auth.api.getSession({ headers });
      expect(session?.user).toMatchObject({ id: fixture.userId, name: "Independent Viewer", image: null });
      expect(session?.session.id).toBe(fixture.sessionId);
      expect(await auth.api.getSession({ headers: new Headers({ cookie: `${fixture.cookieHeader}tampered` }) })).toBeNull();
      const response = await auth.handler(request("/sign-out", {}, fixture.cookieHeader));
      expect(response.status).toBe(200);
      expect(await response.json()).toMatchObject({ success: true });
      expect(response.headers.has("location")).toBe(false);
      expect((await pool.query('SELECT id FROM "session" WHERE id=$1', [fixture.sessionId])).rowCount).toBe(0);
      expect(response.headers.get("set-cookie")).toContain("Max-Age=0");
      expect(response.headers.get("set-cookie")).toContain("__Secure-open-university.session_token=");
      expect(response.headers.get("set-cookie")).toContain("__Secure-open-university.session_data=");
      expect(await auth.api.getSession({ headers })).toBeNull();
    } finally { await fixture.cleanup(); }
  });

  it("caches the session for five minutes but observes DB revocation when explicitly verified", async () => {
    const fixture = await createDatabaseSession({ pool, baseURL, secret });
    try {
      const response = await auth.handler(request("/get-session", undefined, fixture.cookieHeader));
      expect(response.status).toBe(200);
      const cache = response.headers.getSetCookie().find((cookie) => cookie.startsWith("__Secure-open-university.session_data="));
      expect(cache).toBeDefined();
      expect(cache).toContain(`Max-Age=${String(SESSION_CACHE_SECONDS)}`);
      expect(cache).toContain("HttpOnly");
      expect(cache).toContain("Secure");
      expect(cache).toContain("SameSite=Lax");
      const headers = new Headers({ cookie: `${fixture.cookieHeader}; ${cache?.split(";")[0] ?? ""}` });
      await pool.query('DELETE FROM "session" WHERE id=$1', [fixture.sessionId]);
      expect((await auth.api.getSession({ headers }))?.user.id).toBe(fixture.userId);
      expect(await auth.api.getSession({ headers, query: { disableCookieCache: true } })).toBeNull();
    } finally { await fixture.cleanup(); }
  });

  it("refreshes a day-old session to thirty days and preserves privacy", async () => {
    const fixture = await createDatabaseSession({ pool, baseURL, secret });
    try {
      await pool.query('UPDATE "session" SET expires_at=now()+interval \'28 days\', updated_at=now()-interval \'2 days\' WHERE id=$1', [fixture.sessionId]);
      const response = await auth.handler(request("/get-session", undefined, fixture.cookieHeader));
      expect(response.status).toBe(200);
      const row = (await pool.query<{ expires_at: Date; ip_address: string | null; user_agent: string | null }>('SELECT expires_at, ip_address, user_agent FROM "session" WHERE id=$1', [fixture.sessionId])).rows[0];
      expect(row?.expires_at.getTime()).toBeGreaterThan(Date.now() + (SESSION_LIFETIME_SECONDS - 60) * 1000);
      expect(row).toMatchObject({ ip_address: null, user_agent: null });
    } finally { await fixture.cleanup(); }
  });

  it("persists no Google photo, provider tokens, IP address, user agent, or password on create/update", async () => {
    const adapter = (await auth.$context).internalAdapter;
    const user = await adapter.createUser({ name: "Privacy Viewer", email: `${randomBytes(10).toString("hex")}@example.invalid`, image: "https://photo.invalid/avatar.jpg" }, { method: "oauth", oauth: { providerId: "google" } });
    try {
      await adapter.updateUser(user.id, { image: "https://photo.invalid/updated.jpg" });
      const tokenData = { accessToken: "synthetic-access", refreshToken: "synthetic-refresh", idToken: "synthetic-id", password: "synthetic-password", scope: "openid email profile", accessTokenExpiresAt: new Date(), refreshTokenExpiresAt: new Date() };
      const account = await adapter.createAccount({ accountId: user.id, providerId: "google", userId: user.id, ...tokenData });
      await adapter.updateAccount(account.id, tokenData);
      const session = await adapter.createSession(user.id);
      await adapter.updateSession(session.token, { ipAddress: "192.0.2.1", userAgent: "Test Browser" });
      expect((await pool.query('SELECT image FROM "user" WHERE id=$1', [user.id])).rows[0]).toEqual({ image: null });
      expect((await pool.query('SELECT ip_address, user_agent FROM "session" WHERE user_id=$1', [user.id])).rows[0]).toEqual({ ip_address: null, user_agent: null });
      expect((await pool.query('SELECT access_token, refresh_token, id_token, password, scope, access_token_expires_at, refresh_token_expires_at FROM account WHERE id=$1', [account.id])).rows[0]).toEqual({ access_token: null, refresh_token: null, id_token: null, password: null, scope: null, access_token_expires_at: null, refresh_token_expires_at: null });
    } finally { await pool.query('DELETE FROM "user" WHERE id=$1', [user.id]); }
  });

  it("enforces the same rate-limit bucket across independent auth instances", async () => {
    const secondInstance = createTowerAuth(pool, env);
    const ip = "198.51.100.1";
    for (let i = 0; i < 10; i++) {
      const instance = i % 2 ? auth : secondInstance;
      expect((await instance.handler(request("/sign-in/social", createGoogleSignInRequest("/"), undefined, ip))).status).toBe(200);
    }
    const blocked = await secondInstance.handler(request("/sign-in/social", createGoogleSignInRequest("/"), undefined, ip));
    expect(blocked.status).toBe(429);
    expect(Number(blocked.headers.get("x-retry-after"))).toBeGreaterThan(0);
    const row = (await pool.query<{ count: number }>("SELECT count FROM rate_limit WHERE key=$1", [`${ip}|/sign-in/social`])).rows[0];
    expect(row?.count).toBe(10);
    expect((await auth.handler(request("/sign-in/social", createGoogleSignInRequest("/"), undefined, "198.51.100.2"))).status).toBe(200);
    await pool.query("UPDATE rate_limit SET last_request=$1 WHERE key=$2", [Date.now() - 61_000, `${ip}|/sign-in/social`]);
    expect((await secondInstance.handler(request("/sign-in/social", createGoogleSignInRequest("/"), undefined, ip))).status).toBe(200);
  });

  it("does not allow concurrent requests to bypass the DB rate limit", async () => {
    const ip = "198.51.100.3";
    const secondInstance = createTowerAuth(pool, env);
    const responses = await Promise.all(Array.from({ length: 20 }, (_, i) => (i % 2 ? auth : secondInstance).handler(request("/sign-in/social", createGoogleSignInRequest("/"), undefined, ip))));
    expect(responses.filter((response) => response.status === 200)).toHaveLength(10);
    expect(responses.filter((response) => response.status === 429)).toHaveLength(10);
  });

  it("rejects external callback destinations and cross-origin sign-out", async () => {
    expect((await auth.handler(request("/sign-in/social", { provider: "google", callbackURL: "https://evil.invalid" }))).status).toBe(403);
    const fixture = await createDatabaseSession({ pool, baseURL, secret });
    try {
      const req = request("/sign-out", {}, fixture.cookieHeader);
      req.headers.set("origin", "https://evil.invalid");
      expect((await auth.handler(req)).status).toBe(403);
      expect((await pool.query('SELECT id FROM "session" WHERE id=$1', [fixture.sessionId])).rowCount).toBe(1);
    } finally { await fixture.cleanup(); }
  });

  it("uses secure HTTP-only Lax cookies with no domain sharing", () => {
    const { sessionToken } = getCookies(createAuthOptions(pool, env));
    expect(sessionToken.name).toBe("__Secure-open-university.session_token");
    expect(sessionToken.attributes).toMatchObject({ httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: SESSION_LIFETIME_SECONDS });
    expect(sessionToken.attributes.domain).toBeUndefined();
    expect(getCookies(createAuthOptions(pool, { ...env, AUTH_URL: "http://localhost:3100" })).sessionToken.name).toBe("open-university.session_token");
  });

  it("adds rate_limit to an F02-shaped schema without changing an existing session", async () => {
    const fixture = await createDatabaseSession({ pool, baseURL, secret });
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      await client.query("DROP TABLE rate_limit");
      const sql = await readFile(new URL("../../drizzle/0002_auth_rate_limit.sql", import.meta.url), "utf8");
      await client.query(sql);
      expect((await client.query('SELECT token FROM "session" WHERE id=$1', [fixture.sessionId])).rows[0]).toEqual({ token: fixture.token });
      expect((await client.query("SELECT to_regclass('rate_limit') IS NOT NULL AS present")).rows[0]).toEqual({ present: true });
    } finally { await client.query("ROLLBACK"); client.release(); await fixture.cleanup(); }
  });
});
