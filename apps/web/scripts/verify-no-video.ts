import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import type { NoVideoRecord } from "../e2e/fixtures/no-video-policy.ts";
import { summarizeNoVideoRecords } from "./lib/no-video-report.ts";

const dir = path.resolve(import.meta.dirname, "../.reports/no-video");

const files = await readdir(dir).catch(() => [] as string[]);
const records = await Promise.all(
  files.filter((f) => f.endsWith(".json")).map(async (f) => JSON.parse(await readFile(path.join(dir, f), "utf8")) as NoVideoRecord),
);
const summary = summarizeNoVideoRecords(records);
for (const line of summary.lines) console.log(line);
process.exitCode = summary.ok ? 0 : 1;
