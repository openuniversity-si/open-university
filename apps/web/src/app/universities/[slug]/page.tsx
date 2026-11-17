/** A university. A day is only a safety net: release activation purges the layout. */
import { CACHE } from "@/kernel/cache.ts";

export const revalidate = 86_400 satisfies typeof CACHE.directorySeconds;

export { generateMetadata, default } from "./view";
