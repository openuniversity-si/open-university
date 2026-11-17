import { describe, expect, it } from "vitest";
import { ADMIN_CATALOG_ROUTES } from "../catalog/server/routes.ts";
import { cliRoute, CLI_ROUTES } from "../../scripts/lib/catalog-cli/routes.ts";
import { ADMIN_ROUTE_SPECS, matchAdminRoute } from "./route-specs.ts";

const FROZEN = [
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
  "GET /", "POST /", "DELETE /", "POST /check", "POST /objects", "POST /attach", "POST /rollback", "POST /prune-inherited",
];

describe("admin route specs", () => {
  it("freezes the catalog and media operations without duplicate pairs or handler ids", () => {
    expect(ADMIN_ROUTE_SPECS).toHaveLength(77);
    const pairs = ADMIN_ROUTE_SPECS.map((spec) => `${spec.scope} ${spec.method} ${spec.path}`);
    expect(new Set(pairs).size).toBe(77);
    expect(new Set(ADMIN_ROUTE_SPECS.map((spec) => spec.handlerId)).size).toBe(77);
    for (const spec of ADMIN_ROUTE_SPECS) {
      if (spec.action !== null || spec.path === "/preview-token") expect(spec.permission, spec.id).not.toBeNull();
    }
    expect(ADMIN_ROUTE_SPECS.map((spec) => spec.path.startsWith("/api") ? spec.id : `${spec.method} ${spec.path}`)).toEqual(FROZEN);
  });

  it("prefers literal segments over parameters and keeps the media root", () => {
    expect(matchAdminRoute("POST", "/api/admin/catalog/courses/publish-batch")?.spec.path).toBe("/courses/publish-batch");
    expect(matchAdminRoute("GET", "/api/admin/catalog/courses/course-1")?.spec.path).toBe("/courses/:id");
    expect(matchAdminRoute("GET", "/api/admin/catalog/courses/course-1/")?.params).toEqual({ id: "course-1" });
    expect(matchAdminRoute("POST", "/api/admin/catalog/courses/course-1")).toBeNull();
    expect(matchAdminRoute("GET", "/api/admin/media")?.spec.path).toBe("/");
    expect(matchAdminRoute("GET", "/api/admin/media/")?.spec.path).toBe("/");
    expect(matchAdminRoute("POST", "/api/admin/media/check")?.spec.handlerId).toBe("media:POST /check");
    expect(matchAdminRoute("PUT", "/api/admin/media")).toBeNull();
  });

  it("marks every read-only POST safe to retry and no write", () => {
    expect(ADMIN_ROUTE_SPECS.filter((entry) => entry.safe).map((entry) => entry.id)).toEqual([
      "catalog:POST /preview-token", "catalog:POST /media/references",
      "catalog:POST /bundles/validate", "catalog:POST /bundles/diff", "catalog:POST /bundles/export",
      "catalog:POST /lifecycle/inventory", "media:POST /check",
    ]);
    for (const entry of ADMIN_ROUTE_SPECS) {
      if (entry.action !== null || entry.method !== "POST") expect(entry.safe, entry.id).toBe(false);
    }
    expect(cliRoute("POST /bundles/validate").safe).toBe(true);
    expect(cliRoute("POST /redirects").safe).toBe(false);
    expect(cliRoute("POST /courses/:id/status").safe).toBe(false);
    expect(cliRoute("POST /jobs/claim").safe).toBe(false);
  });

  it("projects the CLI table from the same schema objects", () => {
    expect(Object.keys(CLI_ROUTES).sort()).toEqual(ADMIN_CATALOG_ROUTES.map((route) => route.key).sort());
    for (const route of ADMIN_CATALOG_ROUTES) {
      const cli = cliRoute(route.key);
      expect(cli.query, route.key).toBe(route.query);
      expect(cli.body, route.key).toBe(route.body);
      expect(cli.idempotency, route.key).toBe(route.idempotency);
      expect(cli.timeoutMs, route.key).toBeGreaterThan(0);
    }
  });
});
