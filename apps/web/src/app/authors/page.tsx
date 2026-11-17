import { CACHE } from "@/kernel/cache.ts";

/** The Authors tab. Static like the visitor Home; every release activation purges it. */
export const revalidate = 86_400 satisfies typeof CACHE.directorySeconds;

export { metadata, default } from "./view";
