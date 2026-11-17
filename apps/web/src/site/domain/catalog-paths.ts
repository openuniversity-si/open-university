import { PUBLIC_ROUTE_SPECS } from "./route-registry.ts";

export type CatalogPath = readonly [path: string, type?: "layout" | "page"];

/**
 * Static/ISR pages rendered from the active release, purged on every activation.
 * The list is the registry's invalidation entries, in registry order — not a second hand list.
 */
export const CATALOG_PATHS: readonly CatalogPath[] = PUBLIC_ROUTE_SPECS.flatMap((spec) =>
  spec.invalidation.map((entry) => (entry.type ? [entry.path, entry.type] as const : [entry.path] as const)),
);
