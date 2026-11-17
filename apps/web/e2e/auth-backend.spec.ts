import pg from "pg";
import { test, expect } from "./fixtures/no-video-guard.ts";
import { injectSession, TEST_SESSION_SECRET } from "./fixtures/session.ts";
import { validateDatabaseUrl } from "../scripts/lib/database-target.ts";

test("auth back end accepts the injected cookie and sign-out deletes its DB session", async ({ context, page, baseURL }) => {
  const connectionString = process.env.TEST_DATABASE_URL;
  if (!connectionString || !baseURL) throw new Error("TEST_DATABASE_URL and the local Playwright baseURL are required.");
  validateDatabaseUrl(connectionString, "container");
  const pool = new pg.Pool({ connectionString });
  const fixture = await injectSession(context, { pool, baseURL, secret: TEST_SESSION_SECRET });
  try {
    await page.goto("/");
    const sessionResponse = await context.request.get("/api/auth/get-session");
    expect(sessionResponse.status()).toBe(200);
    const data = await sessionResponse.json() as { user: { id: string } };
    expect(data.user.id).toBe(fixture.userId);
    expect(sessionResponse.headers()["cache-control"]).toBe("no-store");
    const signedOut = await context.request.post("/api/auth/sign-out", { data: {}, headers: { origin: baseURL } });
    expect(signedOut.status()).toBe(200);
    expect((await pool.query('SELECT id FROM "session" WHERE id=$1', [fixture.sessionId])).rowCount).toBe(0);
    expect(await (await context.request.get("/api/auth/get-session")).json()).toBeNull();
    expect(page.url()).toBe(`${baseURL}/`);
    expect((await context.cookies()).some((cookie) => ["open-university.session_token", "open-university.session_data"].includes(cookie.name))).toBe(false);
  } finally { await fixture.cleanup(); await pool.end(); }
});

test("auth back end runs with Google sign-in unavailable", async ({ context }) => {
  const response = await context.request.post("/api/auth/sign-in/social", { data: { provider: "google", callbackURL: "/" } });
  expect(response.status()).toBe(503);
  expect(await response.json()).toMatchObject({ code: "GOOGLE_SIGN_IN_UNAVAILABLE" });
});
