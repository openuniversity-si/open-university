import "server-only";
import { currentEnv } from "../../kernel/env.ts";
import { hasDatabase } from "../../platform/db/database-env.ts";
import type { IdentitySession, IdentitySessionPort } from "../ports/session.ts";
import { hasAuthStorage } from "../../identity/domain/settings.ts";
import { getAuth, hasGoogleCredentials } from "./config.ts";

interface AuthSessionReader {
  api: {
    getSession(input: { headers: Headers; query?: { disableCookieCache: true } }): Promise<{ user?: { id?: string }; session?: { expiresAt?: Date | string | number } } | null>;
  };
}

export function isGoogleSignInAvailable(): boolean {
  return hasAuthStorage(currentEnv(), hasDatabase()) && hasGoogleCredentials(currentEnv());
}

function projectSession(session: { user?: { id?: string }; session?: { expiresAt?: Date | string | number } } | null): IdentitySession | null {
  const userId = session?.user?.id;
  if (!session || !userId) return null;
  const expiresAt = session.session?.expiresAt;
  const time = expiresAt instanceof Date ? expiresAt.getTime() : typeof expiresAt === "number" ? expiresAt : Date.parse(expiresAt ?? "");
  return { userId, expiresAt: time };
}

/** `verifyRevocation` skips the cookie cache so a revoked session cannot write. */
export async function sessionFromAuth(auth: AuthSessionReader, requestHeaders: Headers, options: { readonly verifyRevocation: boolean }): Promise<IdentitySession | null> {
  const session = await auth.api.getSession({ headers: requestHeaders, ...(options.verifyRevocation ? { query: { disableCookieCache: true } } : {}) });
  return projectSession(session);
}

export async function getSession(requestHeaders: Headers) {
  const auth = getAuth();
  return auth ? await auth.api.getSession({ headers: requestHeaders }) : null;
}

// Progress writes and other authenticated mutations must observe DB revocation immediately.
export async function getVerifiedSession(requestHeaders: Headers) {
  const auth = getAuth();
  return auth ? auth.api.getSession({ headers: requestHeaders, query: { disableCookieCache: true } }) : null;
}

export function identitySessions(): IdentitySessionPort {
  return {
    session(requestHeaders, options) {
      const auth = getAuth();
      return auth ? sessionFromAuth(auth, requestHeaders, options) : Promise.resolve(null);
    },
  };
}
