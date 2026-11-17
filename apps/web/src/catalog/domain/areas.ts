import type { CatalogTables } from "./tables.ts";
import type { PublicCatalog } from "./release.ts";
import { subareasInOrder } from "./compile.ts";

/**
 * Subject areas (ADR-25, docs/catalog/areas.md): one global, ordered list of single-discipline areas shared by every
 * university. The list and its order are data: the `subject_areas` table is the only source, changed through the admin
 * API (`tower-catalog area create | move | update`), and a release carries it as `areas`. No list of areas lives in code.
 */
type Taxonomy = Pick<CatalogTables, "subject_areas" | "subject_subareas">;

/**
 * Areas and subareas whose place or title in the tables differs from the release (`area:<id>`, `subarea:<id>`, sorted).
 * A release without `areas` (or `subareas`) publishes none, so there is nothing to drift from.
 */
export function taxonomyDrift(release: Pick<PublicCatalog, "areas" | "subareas">, tables: Taxonomy): string[] {
  const stored = {
    area: [...tables.subject_areas].sort((a, b) => a.position - b.position).map((area) => ({ id: area.id, title: area.title })),
    subarea: subareasInOrder(tables),
  };
  const drift = (kind: "area" | "subarea", published: readonly { id: string }[] | undefined, current: readonly { id: string }[]): string[] => {
    if (!published) return [];
    const index = (list: readonly { id: string }[]) => new Map(list.map((entry, position) => [entry.id, JSON.stringify({ ...entry, position })]));
    const [before, after] = [index(published), index(current)];
    return [...new Set([...before.keys(), ...after.keys()])].filter((id) => before.get(id) !== after.get(id)).map((id) => `${kind}:${id}`);
  };
  return [...drift("area", release.areas, stored.area), ...drift("subarea", release.subareas, stored.subarea)].sort();
}
