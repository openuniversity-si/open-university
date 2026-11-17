import type { z } from "zod";
import { jobAdvanceBody, jobClaimBody, jobCompleteBody, jobRenewBody } from "./job-body.ts";
import { lifecycleGcBody, lifecycleResetBody } from "./lifecycle-body.ts";
import type { PermissionKind } from "./permissions.ts";
import { bundleBody } from "../catalog/domain/bundle.ts";
import { shipBatchBody } from "../catalog/domain/ship-batch.ts";
import { applyBatchBody } from "../catalog/domain/batch-v2.ts";
import * as c from "../catalog/domain/contracts.ts";
import { MAX_BODY_BYTES } from "../catalog/domain/contracts.ts";
import { LIMITS } from "../kernel/limits.ts";
import {
  mediaAttachBody, mediaCheckBody, mediaDeleteBody, mediaListQuery, mediaPruneBody, mediaRollbackBody,
  MEDIA_MAX_BYTES,
} from "./media-contracts.ts";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type AdminScope = "catalog" | "media";
export interface AdminRouteSpec {
  readonly id: string;
  readonly handlerId: string;
  readonly scope: AdminScope;
  readonly method: HttpMethod;
  readonly path: string;
  readonly params: z.ZodType;
  readonly query: z.ZodType;
  readonly body: { readonly kind: "none" } | { readonly kind: "json"; readonly schema: z.ZodType; readonly maxBytes: number } | { readonly kind: "multipart"; readonly maxBytes: number };
  readonly idempotency: "none" | "required" | "unless-dry-run";
  readonly action: string | null;
  readonly permission: PermissionKind | null;
  readonly timeoutMs: number;
  /** A POST with no second effect. The CLI repeats it after a dropped connection; a write stays unmarked. */
  readonly safe: boolean;
}

function permissionFor(scope: AdminScope, path: string, action: string | null): PermissionKind | null {
  if (path === "/preview-token") return "catalog:write";
  if (!action) return null;
  if (action === "media.delete" || action === "media.prune") return "media:gc:execute";
  if (scope === "media" || action.startsWith("media.")) return "media:write";
  if (action.startsWith("release.") || action.includes("publish")) return "catalog:publish";
  return "catalog:write";
}

function spec(scope: AdminScope, method: HttpMethod, path: string, idempotency: AdminRouteSpec["idempotency"], action: string | null, params: z.ZodType, query: z.ZodType, body: AdminRouteSpec["body"], timeoutMs: number, retry: "safe" | "default" = "default"): AdminRouteSpec {
  const safe = retry === "safe";
  if (safe && (method !== "POST" || action !== null)) throw new Error(`Only a read-only POST can be marked safe (${scope} ${method} ${path}).`);
  const id = `${method} ${path}`;
  return { id: `${scope}:${id}`, handlerId: `${scope}:${id}`, scope, method, path, params, query, body, idempotency, action, permission: permissionFor(scope, path, action), timeoutMs, safe };
}

const catalog: readonly AdminRouteSpec[] = [
  spec("catalog", "GET", "/courses", "none", null, c.noQuery, c.coursesQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/courses", "required", "course.create", c.noQuery, c.noQuery, { kind: "json", schema: c.courseCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "GET", "/courses/:id", "none", null, c.idParams, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "PATCH", "/courses/:id", "none", "course.update", c.idParams, c.noQuery, { kind: "json", schema: c.coursePatch, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "DELETE", "/courses/:id", "none", "course.delete", c.idParams, c.courseDeleteQuery, { kind: "none" }, LIMITS.adminLongMs),
  spec("catalog", "POST", "/courses/:id/status", "none", "course.status", c.idParams, c.noQuery, { kind: "json", schema: c.courseStatusBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/courses/:id/publish", "required", "course.publish", c.idParams, c.noQuery, { kind: "json", schema: c.publishBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminLongMs),
  spec("catalog", "POST", "/courses/publish-batch", "required", "course.publish.batch", c.noQuery, c.noQuery, { kind: "json", schema: c.publishBatchBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminBatchMs),
  spec("catalog", "POST", "/courses/classify", "required", "course.classify", c.noQuery, c.noQuery, { kind: "json", schema: c.classifyBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/courses/:id/unpublish", "required", "course.unpublish", c.idParams, c.noQuery, { kind: "json", schema: c.unpublishBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminLongMs),
  spec("catalog", "GET", "/courses/:id/editions", "none", null, c.idParams, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/courses/:id/editions", "required", "edition.create", c.idParams, c.noQuery, { kind: "json", schema: c.editionCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "PUT", "/courses/:id/editions/order", "none", "edition.reorder", c.idParams, c.noQuery, { kind: "json", schema: c.editionOrder, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "PATCH", "/editions/:id", "none", "edition.update", c.idParams, c.noQuery, { kind: "json", schema: c.editionPatch, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "DELETE", "/editions/:id", "none", "edition.delete", c.idParams, c.editionDeleteQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "PUT", "/editions/:id/lessons/order", "none", "lesson.reorder", c.idParams, c.noQuery, { kind: "json", schema: c.lessonOrder, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/courses/:id/lessons", "required", "lesson.create", c.idParams, c.noQuery, { kind: "json", schema: c.lessonCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "PUT", "/courses/:id/lessons/order", "none", "lesson.reorder", c.idParams, c.noQuery, { kind: "json", schema: c.lessonOrder, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "PUT", "/lessons/slugs", "required", "lesson.slug", c.noQuery, c.noQuery, { kind: "json", schema: c.lessonSlugsPut, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "PATCH", "/lessons/:id", "none", "lesson.update", c.idParams, c.lessonPatchQuery, { kind: "json", schema: c.lessonPatch, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "DELETE", "/lessons/:id", "none", "lesson.delete", c.idParams, c.lessonDeleteQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "GET", "/authors", "none", null, c.noQuery, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/authors", "required", "author.create", c.noQuery, c.noQuery, { kind: "json", schema: c.authorCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "PATCH", "/authors/:id", "none", "author.update", c.idParams, c.noQuery, { kind: "json", schema: c.authorPatch, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "DELETE", "/authors/:id", "none", "author.delete", c.idParams, c.authorDeleteQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "GET", "/texts", "none", null, c.noQuery, c.textsQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "PUT", "/texts", "none", "text.put", c.noQuery, c.noQuery, { kind: "json", schema: c.textsPut, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/texts/approve", "required", "text.approve", c.noQuery, c.noQuery, { kind: "json", schema: c.textsApprove, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/texts/revoke", "required", "text.revoke", c.noQuery, c.noQuery, { kind: "json", schema: c.textsRevoke, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "GET", "/home", "none", null, c.noQuery, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "PUT", "/home", "none", "home.set", c.noQuery, c.noQuery, { kind: "json", schema: c.homePut, maxBytes: MAX_BODY_BYTES }, LIMITS.adminLongMs),
  spec("catalog", "GET", "/areas", "none", null, c.noQuery, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/areas", "required", "area.create", c.noQuery, c.noQuery, { kind: "json", schema: c.areaCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "PATCH", "/areas/:id", "none", "area.update", c.idParams, c.noQuery, { kind: "json", schema: c.areaPatch, maxBytes: MAX_BODY_BYTES }, LIMITS.adminLongMs),
  spec("catalog", "POST", "/areas/:id/move", "required", "area.move", c.idParams, c.noQuery, { kind: "json", schema: c.areaMove, maxBytes: MAX_BODY_BYTES }, LIMITS.adminLongMs),
  spec("catalog", "GET", "/subareas", "none", null, c.noQuery, c.subareasQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/subareas", "required", "subarea.create", c.noQuery, c.noQuery, { kind: "json", schema: c.subareaCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "GET", "/licenses", "none", null, c.noQuery, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/licenses", "required", "license.create", c.noQuery, c.noQuery, { kind: "json", schema: c.licenseCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "GET", "/sources", "none", null, c.noQuery, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/sources", "required", "source.create", c.noQuery, c.noQuery, { kind: "json", schema: c.sourceCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "PATCH", "/sources/:id", "none", "source.update", c.sourceParams, c.noQuery, { kind: "json", schema: c.sourcePatch, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/imports", "required", "import.create", c.noQuery, c.noQuery, { kind: "json", schema: c.importCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/imports/:id/draft", "required", "import.draft", c.importParams, c.noQuery, { kind: "json", schema: c.importDraft, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "GET", "/releases", "none", null, c.noQuery, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "GET", "/releases/:n", "none", null, c.releaseParams, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/releases", "unless-dry-run", "release.create", c.noQuery, c.releasesCreateQuery, { kind: "json", schema: c.releaseCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminLongMs),
  spec("catalog", "POST", "/releases/:n/activate", "required", "release.activate", c.releaseParams, c.noQuery, { kind: "json", schema: c.releaseActivate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminLongMs),
  spec("catalog", "GET", "/redirects", "none", null, c.noQuery, c.redirectsQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/redirects", "none", "redirect.create", c.noQuery, c.noQuery, { kind: "json", schema: c.redirectCreate, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "DELETE", "/redirects", "none", "redirect.delete", c.noQuery, c.redirectDeleteQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/preview-token", "none", null, c.noQuery, c.noQuery, { kind: "json", schema: c.previewTokenBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs, "safe"),
  spec("catalog", "GET", "/audit", "none", null, c.noQuery, c.auditQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "GET", "/tables", "none", null, c.noQuery, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/media/references", "none", null, c.noQuery, c.noQuery, { kind: "json", schema: c.mediaReferencesBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs, "safe"),
  spec("catalog", "GET", "/doctor", "none", null, c.noQuery, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/bundles/validate", "none", null, c.noQuery, c.noQuery, { kind: "json", schema: bundleBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs, "safe"),
  spec("catalog", "POST", "/bundles/diff", "none", null, c.noQuery, c.noQuery, { kind: "json", schema: bundleBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs, "safe"),
  spec("catalog", "POST", "/bundles/apply", "required", "course.bundle", c.noQuery, c.noQuery, { kind: "json", schema: bundleBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminLongMs),
  spec("catalog", "POST", "/bundles/ship", "required", "course.publish.ship", c.noQuery, c.noQuery, { kind: "json", schema: shipBatchBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminBatchMs),
  spec("catalog", "POST", "/batches/apply", "required", "course.publish.apply", c.noQuery, c.noQuery, { kind: "json", schema: applyBatchBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminBatchMs),
  spec("catalog", "POST", "/bundles/export", "none", null, c.noQuery, c.noQuery, { kind: "json", schema: bundleBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs, "safe"),
  spec("catalog", "POST", "/jobs/claim", "none", "job.claim", c.noQuery, c.noQuery, { kind: "json", schema: jobClaimBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/jobs/:id/renew", "none", "job.renew", c.idParams, c.noQuery, { kind: "json", schema: jobRenewBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/jobs/:id/advance", "required", "job.advance", c.idParams, c.noQuery, { kind: "json", schema: jobAdvanceBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/jobs/:id/complete", "required", "job.complete", c.idParams, c.noQuery, { kind: "json", schema: jobCompleteBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("catalog", "POST", "/lifecycle/inventory", "none", null, c.noQuery, c.noQuery, { kind: "none" }, LIMITS.adminRouteMs, "safe"),
  spec("catalog", "POST", "/lifecycle/gc", "required", "lifecycle.gc", c.noQuery, c.noQuery, { kind: "json", schema: lifecycleGcBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminLongMs),
  spec("catalog", "POST", "/lifecycle/preview-reset", "required", "lifecycle.reset", c.noQuery, c.noQuery, { kind: "json", schema: lifecycleResetBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminLongMs),
];

const media: readonly AdminRouteSpec[] = [
  spec("media", "GET", "/", "none", null, c.noQuery, mediaListQuery, { kind: "none" }, LIMITS.adminRouteMs),
  spec("media", "POST", "/", "required", "media.upload", c.noQuery, c.noQuery, { kind: "multipart", maxBytes: MEDIA_MAX_BYTES }, LIMITS.mediaTransferMs),
  spec("media", "DELETE", "/", "unless-dry-run", "media.delete", c.noQuery, c.noQuery, { kind: "json", schema: mediaDeleteBody, maxBytes: MAX_BODY_BYTES }, LIMITS.mediaTransferMs),
  spec("media", "POST", "/check", "none", null, c.noQuery, c.noQuery, { kind: "json", schema: mediaCheckBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs, "safe"),
  spec("media", "POST", "/objects", "required", "media.object", c.noQuery, c.noQuery, { kind: "multipart", maxBytes: MEDIA_MAX_BYTES }, LIMITS.mediaTransferMs),
  spec("media", "POST", "/attach", "required", "media.attach", c.noQuery, c.noQuery, { kind: "json", schema: mediaAttachBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("media", "POST", "/rollback", "required", "media.rollback", c.noQuery, c.noQuery, { kind: "json", schema: mediaRollbackBody, maxBytes: MAX_BODY_BYTES }, LIMITS.adminRouteMs),
  spec("media", "POST", "/prune-inherited", "unless-dry-run", "media.prune", c.noQuery, c.noQuery, { kind: "json", schema: mediaPruneBody, maxBytes: MAX_BODY_BYTES }, LIMITS.mediaTransferMs),
];

export const ADMIN_ROUTE_SPECS: readonly AdminRouteSpec[] = [...catalog, ...media];

export function cliProjection() {
  return Object.fromEntries(catalog.map((entry) => [`${entry.method} ${entry.path}`, {
    method: entry.method,
    path: entry.path,
    query: entry.query,
    body: entry.body.kind === "json" ? entry.body.schema : null,
    idempotency: entry.idempotency,
    mutates: entry.action !== null,
    safe: entry.safe,
    timeoutMs: entry.timeoutMs,
  }]));
}

/** Literal segments outrank parameters (`publish-batch` before `:id`). Trailing slashes collapse; `/` is the media root. */
export function matchAdminRoute(method: string, pathname: string): { readonly spec: AdminRouteSpec; readonly params: Readonly<Record<string, string>> } | null {
  const scope = pathname.startsWith("/api/admin/media") ? "media" : pathname.startsWith("/api/admin/catalog") ? "catalog" : null;
  if (!scope) return null;
  const base = scope === "media" ? "/api/admin/media" : "/api/admin/catalog";
  let relative = pathname.slice(base.length) || "/";
  if (relative.length > 1 && relative.endsWith("/")) relative = relative.slice(0, -1);
  const parts = relative === "/" ? [] : relative.split("/").filter(Boolean);
  let best: { spec: AdminRouteSpec; params: Record<string, string>; score: number } | null = null;
  for (const spec of ADMIN_ROUTE_SPECS) {
    if (spec.scope !== scope || spec.method !== method) continue;
    const pattern = spec.path === "/" ? [] : spec.path.split("/").filter(Boolean);
    if (pattern.length !== parts.length) continue;
    const params: Record<string, string> = {};
    let score = 0;
    let ok = true;
    for (let i = 0; i < pattern.length; i += 1) {
      const token = pattern[i] ?? "";
      const value = parts[i] ?? "";
      if (token.startsWith(":")) params[token.slice(1)] = value;
      else if (token !== value) { ok = false; break; }
      else score += 2;
    }
    if (ok && (best === null || score > best.score)) best = { spec, params, score };
  }
  return best && { spec: best.spec, params: best.params };
}

export function allowedMethods(pathname: string): readonly string[] {
  const methods = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;
  return methods.filter((method) => matchAdminRoute(method, pathname));
}
