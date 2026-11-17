import "server-only";
import { adminReply } from "@/admin/auth.ts";
import { allowedMethods, matchAdminRoute } from "@/admin/route-specs.ts";
import { adminCatalogDeps } from "@/catalog/server/deps.ts";
import { ADMIN_CATALOG_ROUTES } from "@/catalog/server/routes.ts";
import { REQUEST_ID_HEADER, requestIdFrom } from "@/platform/observability/context.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** One catch-all for every catalog admin method. `defineRoute` still owns parse, idempotency and the transaction. */
export async function handleCatalogAdmin(request: Request, context?: { readonly params?: Promise<unknown> }): Promise<Response> {
  if (context?.params) await context.params;
  const url = new URL(request.url);
  const requestId = requestIdFrom(request.headers.get(REQUEST_ID_HEADER), () => crypto.randomUUID());
  const matched = matchAdminRoute(request.method, url.pathname);
  if (!matched || matched.spec.scope !== "catalog") {
    const allow = allowedMethods(url.pathname);
    if (allow.length) return adminReply({ ok: false, error: { code: "invalid", message: "Method not allowed." }, requestId }, 405, { [REQUEST_ID_HEADER]: requestId, Allow: allow.join(", ") });
    return adminReply({ ok: false, error: { code: "not_found", message: "Unknown admin route." }, requestId }, 404, { [REQUEST_ID_HEADER]: requestId });
  }
  const route = ADMIN_CATALOG_ROUTES.find((entry) => entry.method === matched.spec.method && entry.path === matched.spec.path);
  if (!route) return adminReply({ ok: false, error: { code: "internal", message: "Catalog route is not composed." }, requestId }, 500, { [REQUEST_ID_HEADER]: requestId });
  return route.run(request, matched.params, adminCatalogDeps());
}

export const GET = handleCatalogAdmin;
export const POST = handleCatalogAdmin;
export const PUT = handleCatalogAdmin;
export const PATCH = handleCatalogAdmin;
export const DELETE = handleCatalogAdmin;
