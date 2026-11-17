import "server-only";
import { handleConfigAdmin } from "@/config/server/admin.ts";
import { configAdminDeps } from "@/config/server/deps.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** One catch-all. The handler owns the guard, the parse, and the revision. */
async function delegate(request: Request): Promise<Response> {
  return handleConfigAdmin(request, configAdminDeps());
}

export const GET = delegate;
export const PUT = delegate;
export const POST = delegate;
