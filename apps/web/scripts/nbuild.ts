import { readFileSync, writeFileSync } from "node:fs";
import { exportCourseBundle, validateCourseBundle } from "../src/catalog/domain/bundle.ts";

const source = process.argv[2];
if (!source) {
  console.error("usage: nbuild <bundle.json> [out.json]");
  process.exit(1);
}
const parsed = validateCourseBundle(JSON.parse(readFileSync(source, "utf8")) as unknown);
if (!parsed.ok) {
  console.error(parsed.error.message);
  process.exit(1);
}
const body = JSON.stringify(exportCourseBundle(parsed.value), null, 2);
const out = process.argv[3];
if (out) writeFileSync(out, `${body}\n`);
else console.log(body);
