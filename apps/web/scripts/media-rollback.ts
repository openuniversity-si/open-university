import { argv } from "node:process";

argv.splice(2, 0, "media", "rollback");
await import("./tower-catalog.ts");
