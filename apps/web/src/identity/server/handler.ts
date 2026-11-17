import "server-only";
import { CACHE } from "../../kernel/cache.ts";
import { currentEnv } from "../../kernel/env.ts";
import { requestContextFrom, REQUEST_ID_HEADER } from "../../platform/observability/context.ts";
import { logStructured } from "../../platform/observability/logger.ts";
import { getAuth, hasGoogleCredentials } from "./config.ts";

export async function handleAuthRequest(request: Request): Promise<Response> {
  const context = requestContextFrom(request, "/api/auth/[...all]");
  const noStore = { "Cache-Control": CACHE.responseNoStore, [REQUEST_ID_HEADER]: context.requestId };
  try {
    const auth = getAuth();
    const path = new URL(request.url).pathname;
    if (!auth) {
      if (request.method === "GET" && path === "/api/auth/get-session") return Response.json(null, { headers: noStore });
      return Response.json({ code: "AUTH_UNAVAILABLE", message: "Sign-in is currently unavailable." }, { status: 503, headers: noStore });
    }
    if (!hasGoogleCredentials(currentEnv()) && path === "/api/auth/sign-in/social") {
      return Response.json({ code: "GOOGLE_SIGN_IN_UNAVAILABLE", message: "Google sign-in is currently unavailable." }, { status: 503, headers: noStore });
    }
    const response = await auth.handler(request);
    response.headers.set("Cache-Control", CACHE.responseNoStore);
    response.headers.set(REQUEST_ID_HEADER, context.requestId);
    return response;
  } catch {
    logStructured("error", "AUTH_REQUEST_FAILED", {}, context);
    return Response.json({ code: "AUTH_UNAVAILABLE", message: "Authentication is currently unavailable." }, { status: 503, headers: noStore });
  }
}
