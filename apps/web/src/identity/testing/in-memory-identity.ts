import { AppError } from "../../kernel/errors.ts";
import { createTestClock, type TestClock } from "../../platform/db/testing/in-memory-uow.ts";
import type { IdentitySessionPort } from "../ports/session.ts";
import type { MailerMessage, MailerPort } from "../ports/mailer.ts";
import type { IdentityBench } from "./identity-contract.ts";

interface SessionRow { readonly userId: string; readonly expiresAt: number; revoked: boolean }

/** Sessions and an outbox. Verified reads observe revocation immediately; cached reads do not. */
export function createInMemoryIdentity(clock: TestClock = createTestClock()): IdentityBench {
  let sessions = new Map<string, SessionRow>();
  let messages: MailerMessage[] = [];
  let sequence = 0;
  let failMail = false;
  let closed = false;

  const port: IdentitySessionPort = {
    session(requestHeaders, options) {
      const token = requestHeaders.get("x-session-token");
      const row = token ? sessions.get(token) : undefined;
      if (!row || row.expiresAt <= clock.now()) return Promise.resolve(null);
      if (options.verifyRevocation && row.revoked) return Promise.resolve(null);
      return Promise.resolve({ userId: row.userId, expiresAt: row.expiresAt });
    },
  };
  const mailer: MailerPort = {
    send(message) {
      if (failMail) {
        failMail = false;
        return Promise.reject(new AppError("upstream_failed", "Mail delivery failed."));
      }
      messages.push({ to: message.to, subject: message.subject, html: message.html });
      return Promise.resolve();
    },
  };

  return {
    port, mailer, clock,
    reset() {
      if (closed) throw new Error("The in-memory identity store is closed.");
      sessions = new Map();
      messages = [];
      failMail = false;
      return Promise.resolve();
    },
    dispose() { closed = true; return Promise.resolve(); },
    issue(userId, lifetimeMs) {
      const token = `session-${String(sequence)}`;
      sequence += 1;
      sessions.set(token, { userId, expiresAt: clock.now() + lifetimeMs, revoked: false });
      return Promise.resolve(token);
    },
    revoke(token) {
      const row = sessions.get(token);
      if (row) row.revoked = true;
      return Promise.resolve();
    },
    failNextMail() { failMail = true; },
    outbox() { return Promise.resolve(messages.map((message) => ({ to: message.to, subject: message.subject }))); },
  };
}
