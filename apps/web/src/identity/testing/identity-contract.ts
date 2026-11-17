import { expect } from "vitest";
import { AppError } from "../../kernel/errors.ts";
import type { ContractSuite } from "../../platform/db/testing/uow-contract.ts";
import type { IdentitySessionPort } from "../ports/session.ts";
import type { MailerPort } from "../ports/mailer.ts";

export interface IdentityBench {
  readonly port: IdentitySessionPort;
  readonly mailer: MailerPort;
  readonly clock: { now(): number; advance(milliseconds: number): void };
  reset(): Promise<void>;
  dispose(): Promise<void>;
  issue(userId: string, lifetimeMs: number): Promise<string>;
  revoke(token: string): Promise<void>;
  failNextMail(): void;
  outbox(): Promise<readonly { readonly to: string; readonly subject: string }[]>;
}

function headers(token?: string): Headers {
  const value = new Headers();
  if (token) value.set("x-session-token", token);
  return value;
}

/** Session expiry, revocation and mail failures. The error never includes the recipient or the body. */
export function identityContract(): ContractSuite<IdentityBench> {
  return {
    portId: "IdentitySessionPort",
    cases: [
      { id: "identity.session.absent", async run(harness) {
        expect(await harness.port.session(headers(), { verifyRevocation: true })).toBeNull();
        const token = await harness.issue("user-a", 1_000);
        expect(await harness.port.session(headers("other"), { verifyRevocation: true })).toBeNull();
        expect(await harness.port.session(headers(token), { verifyRevocation: false })).toMatchObject({ userId: "user-a" });
      } },
      { id: "identity.session.expired", async run(harness) {
        const token = await harness.issue("user-a", 5_000);
        harness.clock.advance(5_000);
        expect(await harness.port.session(headers(token), { verifyRevocation: false })).toBeNull();
      } },
      { id: "identity.session.revoked", async run(harness) {
        const token = await harness.issue("user-a", 5_000);
        await harness.revoke(token);
        expect(await harness.port.session(headers(token), { verifyRevocation: true })).toBeNull();
      } },
      { id: "identity.session.cached-revocation", async run(harness) {
        const token = await harness.issue("user-a", 5_000);
        await harness.revoke(token);
        expect(await harness.port.session(headers(token), { verifyRevocation: false })).toMatchObject({ userId: "user-a" });
      } },
      { id: "identity.mail.outbox", async run(harness) {
        await harness.mailer.send({ to: "person@example.com", subject: "Hello", html: "<p>secret</p>" });
        expect(await harness.outbox()).toEqual([{ to: "person@example.com", subject: "Hello" }]);
      } },
      { id: "identity.mail.failure", async run(harness) {
        harness.failNextMail();
        const error = await harness.mailer.send({ to: "person@example.com", subject: "Hello", html: "<p>secret</p>" }).then(() => { throw new Error("expected mail failure"); }, (caught: unknown) => caught);
        expect(error).toBeInstanceOf(AppError);
        expect((error as AppError).message).toBe("Mail delivery failed.");
        expect((error as AppError).message).not.toContain("person@example.com");
        expect((error as AppError).message).not.toContain("secret");
        expect(await harness.outbox()).toEqual([]);
      } },
    ],
  };
}
