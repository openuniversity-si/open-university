import "server-only";
import { notFound, permanentRedirect } from "next/navigation";
import { catalogPathStatus, type PublicRouteSnapshot } from "../domain/route-registry.ts";

/** Layout guard: the caller loads the snapshot. This only turns it into a real 404 or 308, before streaming. */
export function guardCatalogPath(path: string, snapshot: PublicRouteSnapshot): void {
  const status = catalogPathStatus(snapshot, path);
  if (status.kind === "redirect") permanentRedirect(status.to);
  if (status.kind === "missing") notFound();
}
