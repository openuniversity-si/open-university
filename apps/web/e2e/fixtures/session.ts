import { randomBytes, randomUUID } from "node:crypto";
import { getCookies } from "better-auth/cookies";
import { makeSignature } from "better-auth/crypto";
import type { BrowserContext } from "@playwright/test";
import type pg from "pg";
import { AUTH_COOKIE_PREFIX, SESSION_LIFETIME_SECONDS } from "../../src/identity/domain/settings.ts";

// Only the Playwright runner supplies this synthetic value to its local test server.
export const TEST_SESSION_SECRET = "tower-synthetic-session-secret-for-browser-tests";

export interface SessionFixtureOptions {
  pool: pg.Pool;
  baseURL: string;
  secret: string;
  name?: string;
}

// Test-runner only: creates a unique synthetic DB identity, never an app login endpoint.
export async function createDatabaseSession({ pool, baseURL, secret, name = "Test Viewer" }: SessionFixtureOptions) {
  const userId = randomUUID();
  const sessionId = randomUUID();
  const token = randomBytes(32).toString("base64url");
  const expiresAt = new Date(Date.now() + SESSION_LIFETIME_SECONDS * 1000);
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query('INSERT INTO "user" (id, name, email, email_verified) VALUES ($1, $2, $3, true)', [userId, name, `${userId}@example.invalid`]);
    await client.query('INSERT INTO "session" (id, user_id, token, expires_at) VALUES ($1, $2, $3, $4)', [sessionId, userId, token, expiresAt]);
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally { client.release(); }
  const configuredCookie = getCookies({
    baseURL,
    session: { expiresIn: SESSION_LIFETIME_SECONDS },
    advanced: { cookiePrefix: AUTH_COOKIE_PREFIX, useSecureCookies: baseURL.startsWith("https:") },
  }).sessionToken;
  const cookie = {
    name: configuredCookie.name,
    value: encodeURIComponent(`${token}.${await makeSignature(token, secret)}`),
    url: baseURL,
    httpOnly: true,
    secure: configuredCookie.attributes.secure,
    sameSite: "Lax" as const,
    expires: Math.floor(expiresAt.getTime() / 1000),
  };
  return {
    userId, sessionId, token, cookie,
    cookieHeader: `${cookie.name}=${cookie.value}`,
    cleanup: async () => { await pool.query('DELETE FROM "user" WHERE id = $1', [userId]); },
  };
}

export async function injectSession(context: BrowserContext, options: SessionFixtureOptions) {
  const fixture = await createDatabaseSession(options);
  try { await context.addCookies([fixture.cookie]); } catch (error) { await fixture.cleanup(); throw error; }
  return fixture;
}
