import { registerSignInRedirect, registerSignInRequest } from "../ports/sign-in.ts";

const providerOrigin = "https://accounts.google.com";

const INTERNAL_ORIGIN = "https://return.invalid";
const FEEDBACK_PARAMETERS = ["error", "error_description"];

function hasUnsafeCharacter(value: string): boolean {
  for (const character of value) {
    if (character === "\\" || character.charCodeAt(0) <= 32 || character.charCodeAt(0) === 127) return true;
  }
  return false;
}

export function isSafeReturnRoute(route: string): boolean {
  if (!route.startsWith("/") || route.startsWith("//") || hasUnsafeCharacter(route)) return false;
  try {
    const url = new URL(route, INTERNAL_ORIGIN);
    const decodedPath = decodeURIComponent(url.pathname);
    return url.origin === INTERNAL_ORIGIN && !decodedPath.startsWith("//") && !hasUnsafeCharacter(decodedPath);
  } catch { return false; }
}

function internalRoute(route: string): URL {
  return new URL(isSafeReturnRoute(route) ? route : "/", INTERNAL_ORIGIN);
}

function routeString(url: URL): string {
  return `${url.pathname}${url.search}${url.hash}`;
}

export function normalizePlaybackSecond(second: number): number {
  return Number.isFinite(second) && second >= 0 && second <= Number.MAX_SAFE_INTEGER ? Math.floor(second) : 0;
}

export function getAuthReturnContext(route: string, currentSecond?: number) {
  const url = internalRoute(route);
  for (const parameter of FEEDBACK_PARAMETERS) url.searchParams.delete(parameter);
  const isPlayer = /^\/c\/[^/]+\/[^/]+\/?$/.test(url.pathname);
  const positionSeconds = isPlayer ? normalizePlaybackSecond(currentSecond ?? Number(url.searchParams.get("t") ?? 0)) : 0;
  if (isPlayer) url.searchParams.set("t", String(positionSeconds));
  return { returnTo: routeString(url), positionSeconds, paused: true as const, completeLesson: false as const };
}

// D2 never completes a lesson as a consequence of authenticating. D11 restores paused.
export function createGoogleSignInRequest(route: string, currentSecond?: number) {
  const { returnTo } = getAuthReturnContext(route, currentSecond);
  return { provider: "google" as const, callbackURL: returnTo, newUserCallbackURL: returnTo, errorCallbackURL: returnTo };
}

export function isGoogleSignInRedirect(url: URL): boolean {
  return url.origin === providerOrigin;
}

registerSignInRequest(createGoogleSignInRequest);
registerSignInRedirect(isGoogleSignInRedirect);

export function consumeSignInFeedback(route: string) {
  const url = internalRoute(route);
  const error = url.searchParams.get("error");
  const feedback = error ? (["access_denied", "user_cancelled", "cancelled"].includes(error) ? "cancelled" as const : "error" as const) : null;
  for (const parameter of FEEDBACK_PARAMETERS) url.searchParams.delete(parameter);
  return { feedback, returnTo: routeString(url) };
}
