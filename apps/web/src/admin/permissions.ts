import { AppError } from "../kernel/errors.ts";
import type { AdminEnvironment } from "./ports/jobs.ts";

export const ADMIN_PERMISSIONS = [
  "catalog:write:preview", "catalog:publish:preview", "catalog:write:prod", "catalog:publish:prod", "media:write", "media:gc:execute",
] as const;
export type AdminPermission = (typeof ADMIN_PERMISSIONS)[number];
export type PermissionKind = "catalog:write" | "catalog:publish" | "media:write" | "media:gc:execute";

export interface AdminIdentity {
  readonly actorId: string;
  readonly environment: AdminEnvironment;
  readonly scopes: readonly AdminPermission[];
}

export function scopedPermission(kind: PermissionKind, environment: AdminEnvironment): AdminPermission {
  if (kind === "media:write" || kind === "media:gc:execute") return kind;
  return `${kind}:${environment}`;
}

/** Deny by default. The environment is the credential's, never a value the client chose. */
export function verifyAdminScope(identity: AdminIdentity, permission: AdminPermission, environment: AdminEnvironment): void {
  if (identity.environment !== environment || !identity.scopes.includes(permission)) {
    throw new AppError("forbidden", "This credential cannot perform that operation in this environment.");
  }
}

/**
 * The admin key a deployment accepts is that deployment's operator key: it acts in that environment only,
 * with that environment's scopes. A preview key is refused in prod because prod never resolves to preview.
 */
export function operatorIdentity(actorId: string, environment: AdminEnvironment): AdminIdentity {
  return { actorId, environment, scopes: [scopedPermission("catalog:write", environment), scopedPermission("catalog:publish", environment), "media:write", "media:gc:execute"] };
}

/** An explicit identity wins (a scoped credential); otherwise the operator of the deployment's environment. Unset is preview (tests, local). */
export function requestIdentity(deps: { readonly adminIdentity?: AdminIdentity; readonly environment?: AdminEnvironment }, actorId: string): AdminIdentity {
  return deps.adminIdentity ?? operatorIdentity(actorId, deps.environment ?? "preview");
}
