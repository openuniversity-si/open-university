// Proves a lesson reslug on a live site with reads only (BRIEF-P7 §3; docs/catalog/slugs.md, runbook):
//   node scripts/verify-slug-redirects.ts --base https://openuniversity.si --fixture
//   node scripts/verify-slug-redirects.ts --base <preview url> --pairs pairs.json [--pause-ms 150]
// --fixture checks every changed row of src/catalog/slug.fixtures.json (currentSlug → expectedSlug); --pairs takes a JSON
// array of { from, to } lesson paths, e.g. `tower-catalog lesson reslug … --apply --json | jq '[.data.batches[].data.plan.created[]]'`.
import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";
import type { SlugFixture } from "../src/catalog/testing/slug-fixture.ts";
import { parsePairs, verifySlugRedirects, type SlugPair } from "./lib/slug-redirects.ts";

const { values } = parseArgs({ options: { base: { type: "string" }, pairs: { type: "string" }, fixture: { type: "boolean" }, "pause-ms": { type: "string" } } });
if (!values.base || Boolean(values.pairs) === Boolean(values.fixture)) {
  console.error("usage: node scripts/verify-slug-redirects.ts --base <url> (--pairs <file.json> | --fixture) [--pause-ms 150]");
  process.exit(2);
}
let pairs: SlugPair[];
if (values.fixture) {
  const fixture = JSON.parse(readFileSync(new URL("../src/catalog/testing/slug.fixtures.json", import.meta.url), "utf8")) as SlugFixture;
  pairs = fixture.lessons.filter((row) => row.currentSlug !== row.expectedSlug).map((row) => ({ from: `/c/${row.courseSlug}/${row.currentSlug}`, to: `/c/${row.courseSlug}/${row.expectedSlug}` }));
} else {
  pairs = parsePairs(JSON.parse(readFileSync(values.pairs ?? "", "utf8")));
}
const report = await verifySlugRedirects({
  base: values.base, pairs, fetch, sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  ...(values["pause-ms"] ? { pauseMs: Number(values["pause-ms"]) } : {}),
});
for (const line of report.lines) console.log(line);
process.exitCode = report.ok ? 0 : 1;
