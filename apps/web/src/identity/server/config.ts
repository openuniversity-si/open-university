import "server-only";
import { AppError } from "../../kernel/errors.ts";
import { currentEnv, type EnvInput } from "../../kernel/env.ts";
import { logStructured } from "../../platform/observability/logger.ts";
import type { MailerPort } from "../ports/mailer.ts";
import type { SessionDatabase } from "../ports/session-database.ts";
import { configuredMailer } from "./mailer.ts";
import { betterAuth, type BetterAuthOptions } from "better-auth";
import { APIError, createAuthMiddleware } from "better-auth/api";
import { nextCookies } from "better-auth/next-js";
import { hasDatabase } from "../../platform/db/database-env.ts";
import { appPool } from "../../platform/db/pool.ts";
import { sessionAddressHeaders } from "../../platform/host/request-address.ts";
import { minimizeAccount, minimizeSession, minimizeUser } from "../../identity/domain/privacy.ts";
import { isSafeReturnRoute } from "../../identity/client/return-to.ts";
import { PRODUCTION_ORIGIN } from "../../site/domain/origin.ts";
import {
  AUTH_COOKIE_PREFIX, SESSION_CACHE_SECONDS, SESSION_LIFETIME_SECONDS, SESSION_UPDATE_AGE_SECONDS,
  hasAuthStorage, resolveAuthBaseURL, type AuthEnvironment,
} from "../../identity/domain/settings.ts";

/** Scopes requested on the consent screen. The list is the one the provider adapter sends today. */
export const GOOGLE_SCOPES = ["openid", "email", "profile"];

export function hasGoogleCredentials(env: AuthEnvironment): boolean {
  return Boolean(env.AUTH_GOOGLE_ID?.trim() && env.AUTH_GOOGLE_SECRET?.trim());
}

function hiddenSecret(value: string): { readonly present: boolean; readonly read: () => string } {
  return { present: value.length > 0, read: () => value };
}

/** Session secret profile. A passed map is the fixture; an omitted map is the kernel facade. */
export function getAuthEnv(input?: EnvInput): Readonly<{ configured: boolean; googleConfigured: boolean; secret: ReturnType<typeof hiddenSecret> }> {
  const env = input ?? currentEnv();
  const secret = env.AUTH_SECRET?.trim() ?? "";
  if (secret && secret.length < 32) throw new AppError("invalid", "AUTH_SECRET is invalid.");
  return {
    configured: secret.length > 0,
    googleConfigured: hasGoogleCredentials(env),
    secret: hiddenSecret(secret),
  };
}

export function createAuthOptions(pool: SessionDatabase, env: AuthEnvironment): BetterAuthOptions {
  const baseURL = resolveAuthBaseURL(env.AUTH_URL, PRODUCTION_ORIGIN);
  const googleID = env.AUTH_GOOGLE_ID?.trim();
  const googleSecret = env.AUTH_GOOGLE_SECRET?.trim();
  if (!env.AUTH_SECRET || env.AUTH_SECRET.length < 32) throw new Error("AUTH_SECRET must contain at least 32 characters.");
  return {
    appName: "Open University",
    baseURL,
    basePath: "/api/auth",
    secret: env.AUTH_SECRET,
    database: pool,
    trustedOrigins: [baseURL],
    emailAndPassword: { enabled: false },
    plugins: [nextCookies()],
    socialProviders: hasGoogleCredentials(env) && googleID && googleSecret ? {
      google: {
        clientId: googleID,
        clientSecret: googleSecret,
        scope: GOOGLE_SCOPES,
        disableDefaultScope: true,
        disableIdTokenSignIn: true,
        accessType: "online",
        includeGrantedScopes: false,
      },
    } : {},
    user: { fields: { emailVerified: "email_verified", createdAt: "created_at", updatedAt: "updated_at" } },
    session: {
      fields: { userId: "user_id", expiresAt: "expires_at", createdAt: "created_at", updatedAt: "updated_at", ipAddress: "ip_address", userAgent: "user_agent" },
      expiresIn: SESSION_LIFETIME_SECONDS,
      updateAge: SESSION_UPDATE_AGE_SECONDS,
      storeSessionInDatabase: true,
      preserveSessionInDatabase: false,
      cookieCache: { enabled: true, maxAge: SESSION_CACHE_SECONDS, strategy: "compact", refreshCache: false },
    },
    account: {
      fields: {
        accountId: "account_id", providerId: "provider_id", userId: "user_id",
        accessToken: "access_token", refreshToken: "refresh_token", idToken: "id_token",
        accessTokenExpiresAt: "access_token_expires_at", refreshTokenExpiresAt: "refresh_token_expires_at",
        createdAt: "created_at", updatedAt: "updated_at",
      },
      accountLinking: { enabled: false },
      storeStateStrategy: "database",
      storeAccountCookie: false,
    },
    verification: { fields: { expiresAt: "expires_at", createdAt: "created_at", updatedAt: "updated_at" } },
    rateLimit: {
      enabled: true, storage: "database", modelName: "rate_limit", fields: { lastRequest: "last_request" },
      window: 60, max: 100,
      customRules: { "/sign-in/social": { window: 60, max: 10 } },
    },
    advanced: {
      cookiePrefix: AUTH_COOKIE_PREFIX,
      useSecureCookies: baseURL.startsWith("https:"),
      defaultCookieAttributes: { httpOnly: true, sameSite: "lax", path: "/" },
      disableCSRFCheck: false,
      disableOriginCheck: false,
      ipAddress: { ipAddressHeaders: [...sessionAddressHeaders()], disableIpTracking: false },
    },
    databaseHooks: {
      user: {
        create: { before: (data) => Promise.resolve({ data: minimizeUser(data) }) },
        update: { before: (data) => Promise.resolve({ data: minimizeUser(data) }) },
      },
      session: {
        create: { before: (data) => Promise.resolve({ data: minimizeSession(data) }) },
        update: { before: (data) => Promise.resolve({ data: minimizeSession(data) }) },
      },
      account: {
        create: { before: (data) => {
          if (data.providerId !== "google") throw new APIError("BAD_REQUEST", { message: "Only Google accounts are supported." });
          return Promise.resolve({ data: minimizeAccount(data) });
        } },
        update: { before: (data) => Promise.resolve({ data: minimizeAccount(data) }) },
      },
    },
    hooks: { before: createAuthMiddleware((context) => {
      if (context.path === "/sign-in/social") {
        const body = context.body as { provider?: string; scopes?: string[]; additionalParams?: unknown; callbackURL?: string; newUserCallbackURL?: string; errorCallbackURL?: string } | undefined;
        if (body?.provider !== "google" || body.scopes?.some((scope) => !GOOGLE_SCOPES.includes(scope)) || body.additionalParams) {
          throw new APIError("BAD_REQUEST", { message: "Only Google sign-in with basic identity scopes is supported." });
        }
        for (const route of [body.callbackURL, body.newUserCallbackURL, body.errorCallbackURL]) {
          if (route !== undefined && !isSafeReturnRoute(route)) throw new APIError("FORBIDDEN", { message: "Sign-in must return to a local route." });
        }
      }
      return Promise.resolve();
    }) },
    // Library diagnostics can include provider tokens or driver details. Emit fixed codes only.
    logger: { log: (level) => {
      if (level === "error" || level === "warn") logStructured("error", "AUTH_LIBRARY_DIAGNOSTIC", { level });
    } },
  };
}

export function createTowerAuth(pool: SessionDatabase, env: AuthEnvironment) {
  return betterAuth(createAuthOptions(pool, env));
}

export type TowerAuth = ReturnType<typeof createTowerAuth>;
let configuredAuth: TowerAuth | undefined;

// Lazy initialization keeps builds and public routes independent of OAuth and DB configuration.
/** The configured sender. Nothing is sent until a mail vendor is attached to this port. */
export function authMailer(): MailerPort {
  return configuredMailer();
}

export function getAuth(): TowerAuth | null {
  if (!hasAuthStorage(currentEnv(), hasDatabase())) return null;
  configuredAuth ??= createTowerAuth(appPool(), currentEnv());
  return configuredAuth;
}
