import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { isSignInRedirect } from "../ports/sign-in.ts";
import { consumeSignInFeedback, createGoogleSignInRequest, getAuthReturnContext, isGoogleSignInRedirect, normalizePlaybackSecond } from "./return-to.ts";

describe("same-route OAuth context (D2/D11)", () => {
  it.each(["/", "/c/genesis", "/c/genesis?selection=4#lectures"])("keeps public context %s", (route) => {
    expect(getAuthReturnContext(route, 3134)).toEqual({ returnTo: route, positionSeconds: 0, paused: true, completeLesson: false });
  });

  it("restores the current player second, paused, without completing the lecture", () => {
    expect(getAuthReturnContext("/c/genesis/lecture-4?t=2&selection=4#lectures", 3134.9)).toEqual({
      returnTo: "/c/genesis/lecture-4?t=3134&selection=4#lectures", positionSeconds: 3134, paused: true, completeLesson: false,
    });
  });

  it("uses the saved query second when there is no live player position", () => {
    expect(getAuthReturnContext("/c/genesis/lecture-4?t=3134").positionSeconds).toBe(3134);
  });

  it.each([NaN, Infinity, -Infinity, -1, Number.MAX_SAFE_INTEGER + 1])("resets invalid position %s to zero", (second) => {
    expect(normalizePlaybackSecond(second)).toBe(0);
    expect(getAuthReturnContext("/c/genesis/lecture-4?t=3134", second).returnTo).toBe("/c/genesis/lecture-4?t=0");
  });

  it.each(["-1", "NaN", "Infinity", "garbage"])("resets malformed query t=%s", (second) => {
    expect(getAuthReturnContext(`/c/genesis/lecture-4?t=${second}`).positionSeconds).toBe(0);
  });

  it("sets the same destination for success, first sign-in, and failure", () => {
    expect(createGoogleSignInRequest("/c/genesis/lecture-4?error=access_denied", 52)).toEqual({
      provider: "google", callbackURL: "/c/genesis/lecture-4?t=52", newUserCallbackURL: "/c/genesis/lecture-4?t=52", errorCallbackURL: "/c/genesis/lecture-4?t=52",
    });
  });

  it.each(["https://evil.invalid", "//evil.invalid", "/\\evil.invalid", "/%2f%2fevil.invalid", "/%5cevil.invalid", "/\nevil.invalid", " /c/genesis", "/%00", "/%zz"])("rejects unsafe return route %s", (route) => {
    expect(getAuthReturnContext(route).returnTo).toBe("/");
  });
});

describe("one-use login feedback", () => {
  it.each(["access_denied", "user_cancelled", "cancelled"])("classifies cancellation %s and removes only OAuth feedback", (error) => {
    const result = consumeSignInFeedback(`/c/genesis/lecture-4?t=52&error=${error}&error_description=private&selection=4#lectures`);
    expect(result).toEqual({ feedback: "cancelled", returnTo: "/c/genesis/lecture-4?t=52&selection=4#lectures" });
    expect(consumeSignInFeedback(result.returnTo).feedback).toBeNull();
  });
  it("classifies other failures without exposing the provider description", () => {
    expect(consumeSignInFeedback("/?error=state_mismatch&error_description=details")).toEqual({ feedback: "error", returnTo: "/" });
  });
  it("has no feedback for a normal route", () => {
    expect(consumeSignInFeedback("/c/genesis#lectures")).toEqual({ feedback: null, returnTo: "/c/genesis#lectures" });
  });
});

describe("provider redirect", () => {
  it("accepts only the registered provider origin", () => {
    const allowed = new URL("https://accounts.google.com/o/oauth2/v2/auth");
    expect(isGoogleSignInRedirect(allowed)).toBe(true);
    expect(isSignInRedirect(allowed)).toBe(true);
    expect(isSignInRedirect(new URL("https://accounts.google.com.evil.invalid/"))).toBe(false);
    expect(isSignInRedirect(new URL("https://evil.invalid/"))).toBe(false);
  });

  it("keeps the provider origin in the client adapter", () => {
    const root = fileURLToPath(new URL("../../..", import.meta.url));
    const screen = readFileSync(join(root, "src/identity/client/AuthProvider.tsx"), "utf8");
    const adapter = readFileSync(join(root, "src/identity/client/return-to.ts"), "utf8");
    const server = readFileSync(join(root, "src/identity/server/config.ts"), "utf8");
    expect(screen.includes("accounts.google.com")).toBe(false);
    expect(adapter.includes("accounts.google.com")).toBe(true);
    expect(adapter.includes('provider: "google"')).toBe(true);
    expect(server.includes('providerId !== "google"')).toBe(true);
    expect(server.includes('body?.provider !== "google"')).toBe(true);
  });
});
