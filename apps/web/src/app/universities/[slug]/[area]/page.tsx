/** Every course of one university in one subject area. Purged with the universities layout. */
import { CACHE } from "@/kernel/cache.ts";

export const revalidate = 86_400 satisfies typeof CACHE.directorySeconds;

export { generateMetadata, default } from "./view";
