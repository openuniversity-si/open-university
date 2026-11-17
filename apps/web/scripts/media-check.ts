import { argv } from "node:process";

argv.splice(2, 0, "media", "check");
await import("./tower-catalog.ts");
