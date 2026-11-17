import "server-only";
import { mediaDispatchDeps } from "@/admin/deps.ts";
import { dispatchAdminRequest } from "@/admin/http-dispatcher.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Optional catch-all so GET/POST/DELETE `/api/admin/media` and the five POST subpaths share one file. */
export function handleMediaAdmin(request: Request): Promise<Response> {
  return dispatchAdminRequest(request, mediaDispatchDeps());
}

export const GET = handleMediaAdmin;
export const POST = handleMediaAdmin;
export const PUT = handleMediaAdmin;
export const PATCH = handleMediaAdmin;
export const DELETE = handleMediaAdmin;
