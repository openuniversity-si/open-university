import { argv } from "node:process";

argv.splice(2, 0, "media", "put");
await import("./tower-catalog.ts");
