import { describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ headers: () => Promise.resolve(new Headers()) }));
import { sessionFromAuth } from "./session.ts";

describe("identity session port", () => {
  it("disables the cookie cache only when the write must see revocation", async () => {
    const headers = new Headers({ cookie: "session" });
    const getSession = vi.fn(() => Promise.resolve({ user: { id: "user-1" }, session: { expiresAt: new Date(5_000) } }));
    const auth = { api: { getSession } };
    await expect(sessionFromAuth(auth, headers, { verifyRevocation: true })).resolves.toEqual({ userId: "user-1", expiresAt: 5_000 });
    expect(getSession).toHaveBeenCalledWith({ headers, query: { disableCookieCache: true } });
    await sessionFromAuth(auth, headers, { verifyRevocation: false });
    expect(getSession).toHaveBeenLastCalledWith({ headers });
  });
});
