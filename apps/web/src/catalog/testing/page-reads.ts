import { getCatalog } from "./fake.ts";

/** Unit tests render public pages from the fake release. The SQL reader is not on this graph. */
export function readPageCatalog(): ReturnType<typeof getCatalog> {
  return getCatalog();
}
