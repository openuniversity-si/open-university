import { expireTag } from "../../platform/freshness/next.ts";
import { CACHE } from "../../kernel/cache.ts";
import type { ConfigKind } from "../domain/documents.ts";
import { CONFIG_TAG, configTag } from "./read.ts";

/** A configuration write is visible on the next read. The expiry is the immediate one. */
export function invalidateConfig(kind: ConfigKind): void {
  expireTag(CONFIG_TAG, { expire: CACHE.immediateExpiry });
  expireTag(configTag(kind), { expire: CACHE.immediateExpiry });
}
