import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ADMIN_ROUTE_SPECS } from "../../admin/route-specs.ts";
import { adminCatalogRoute, ADMIN_CATALOG_ROUTES } from "./routes.ts";

const admin = fileURLToPath(new URL("../../app/api/admin", import.meta.url));

function routeFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? routeFiles(full) : name === "route.ts" ? [full] : [];
  });
}

describe("admin catalog routes", () => {
  it("has a route.ts export for every route of routes.ts, and nothing else", () => {
    const files = routeFiles(admin);
    expect(files.map((file) => path.relative(admin, file)).sort()).toEqual(["catalog/[...route]/route.ts", "config/[...route]/route.ts", "media/[[...route]]/route.ts"]);
    const catalog = ADMIN_ROUTE_SPECS.filter((spec) => spec.scope === "catalog");
    expect(catalog.map((spec) => `${spec.method} ${spec.path}`).sort()).toEqual(ADMIN_CATALOG_ROUTES.map((route) => route.key).sort());
    for (const route of ADMIN_CATALOG_ROUTES) {
      const spec = catalog.find((entry) => `${entry.method} ${entry.path}` === route.key);
      expect(spec?.action, route.key).toBe(route.action);
      expect(spec?.idempotency, route.key).toBe(route.idempotency);
      expect(spec?.query, route.key).toBe(route.query);
      expect(spec?.body.kind === "json" ? spec.body.schema : null, route.key).toBe(route.body);
    }
  });

  it("keeps every route.ts thin: nodejs runtime, never cached, only delegating", () => {
    for (const file of routeFiles(admin)) {
      const source = readFileSync(file, "utf8");
      expect(source, file).toContain('export const runtime = "nodejs";');
      expect(source, file).toContain('export const dynamic = "force-dynamic";');
      expect(source, file).not.toContain("authorizeAdmin");
      expect(source.split("\n").filter((line) => line.includes("sql") || line.includes("SELECT ")), file).toEqual([]);
    }
  });

  it("covers every route of plan §3.2", () => {
    expect(ADMIN_CATALOG_ROUTES.map((route) => route.key)).toEqual([
      "GET /courses", "POST /courses", "GET /courses/:id", "PATCH /courses/:id", "DELETE /courses/:id", "POST /courses/:id/status", "POST /courses/:id/publish",
      "POST /courses/publish-batch", "POST /courses/classify", "POST /courses/:id/unpublish", "GET /courses/:id/editions", "POST /courses/:id/editions", "PUT /courses/:id/editions/order", "PATCH /editions/:id",
      "DELETE /editions/:id", "PUT /editions/:id/lessons/order", "POST /courses/:id/lessons", "PUT /courses/:id/lessons/order", "PUT /lessons/slugs", "PATCH /lessons/:id",
      "DELETE /lessons/:id", "GET /authors", "POST /authors", "PATCH /authors/:id", "DELETE /authors/:id", "GET /texts", "PUT /texts", "POST /texts/approve", "POST /texts/revoke",
      "GET /home", "PUT /home", "GET /areas", "POST /areas", "PATCH /areas/:id", "POST /areas/:id/move", "GET /subareas", "POST /subareas", "GET /licenses", "POST /licenses", "GET /sources", "POST /sources", "PATCH /sources/:id", "POST /imports", "POST /imports/:id/draft",
      "GET /releases", "GET /releases/:n", "POST /releases", "POST /releases/:n/activate", "GET /redirects", "POST /redirects", "DELETE /redirects",
      "POST /preview-token", "GET /audit", "GET /tables", "POST /media/references", "GET /doctor",
      "POST /bundles/validate", "POST /bundles/diff", "POST /bundles/apply", "POST /bundles/ship", "POST /batches/apply", "POST /bundles/export",
      "POST /jobs/claim", "POST /jobs/:id/renew", "POST /jobs/:id/advance", "POST /jobs/:id/complete",
      "POST /lifecycle/inventory", "POST /lifecycle/gc", "POST /lifecycle/preview-reset",
    ]);
  });

  it("requires an Idempotency-Key exactly where the brief does", () => {
    expect(ADMIN_CATALOG_ROUTES.filter((route) => route.idempotency !== "none").map((route) => `${route.key}${route.idempotency === "unless-dry-run" ? " (not dry-run)" : ""}`)).toEqual([
      "POST /courses", "POST /courses/:id/publish", "POST /courses/publish-batch", "POST /courses/classify", "POST /courses/:id/unpublish", "POST /courses/:id/editions", "POST /courses/:id/lessons", "PUT /lessons/slugs", "POST /authors", "POST /texts/approve", "POST /texts/revoke",
      "POST /areas", "POST /areas/:id/move", "POST /subareas", "POST /licenses", "POST /sources", "POST /imports", "POST /imports/:id/draft", "POST /releases (not dry-run)", "POST /releases/:n/activate",
      "POST /bundles/apply", "POST /bundles/ship", "POST /batches/apply", "POST /jobs/:id/advance", "POST /jobs/:id/complete",
      "POST /lifecycle/gc", "POST /lifecycle/preview-reset",
    ]);
  });

  it("names an audit action for every mutation and none for reads", () => {
    for (const route of ADMIN_CATALOG_ROUTES) {
      const bundleRead = route.key === "POST /bundles/validate" || route.key === "POST /bundles/diff" || route.key === "POST /bundles/export";
      const lifecycleRead = route.key === "POST /lifecycle/inventory";
      if (route.method === "GET" || route.key === "POST /preview-token" || route.key === "POST /media/references" || bundleRead || lifecycleRead) expect(route.action, route.key).toBeNull();
      else expect(route.action, route.key).toMatch(/^(course|edition|lesson|author|text|home|release|redirect|area|subarea|license|source|import|job|lifecycle)\.[a-z.]+$/);
    }
    expect(() => adminCatalogRoute("GET /nope")).toThrow("Unknown admin catalog route GET /nope.");
  });
});
