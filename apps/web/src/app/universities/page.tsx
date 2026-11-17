/** The Universities tab. Static like the visitor Home; every release activation purges it. */
import { CACHE } from "@/kernel/cache.ts";

export const revalidate = 86_400 satisfies typeof CACHE.directorySeconds;

export { metadata, default } from "./view";
