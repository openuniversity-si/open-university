// Recomputes expectedSlug in src/catalog/testing/slug.fixtures.json from the rows' own inputs (no network, no database).
// After a deliberate change to the rule: `node scripts/lib/slug-fixtures.ts`, then review every changed row in `git diff`.
import { readFileSync, writeFileSync } from "node:fs";
import { fixtureSlugs, type SlugFixture } from "../../src/catalog/testing/slug-fixture.ts";

const path = new URL("../../src/catalog/testing/slug.fixtures.json", import.meta.url);
const text = readFileSync(path, "utf8");
const fixture = JSON.parse(text) as SlugFixture;
const slugs = fixtureSlugs(fixture);
let changed = 0;
const lines = text.split("\n").map((line) => {
  const match = /^ {4}(\{"courseSlug".*\})(,?)$/.exec(line);
  if (!match?.[1]) return line;
  const row = JSON.parse(match[1]) as SlugFixture["lessons"][number];
  const expectedSlug = slugs.get(row.lessonId) ?? row.expectedSlug;
  if (expectedSlug === row.expectedSlug) return line;
  changed += 1;
  return `    ${JSON.stringify({ ...row, expectedSlug })}${match[2] ?? ""}`;
});
writeFileSync(path, lines.join("\n"));
console.log(`${String(changed)} expectedSlug value(s) changed of ${String(fixture.lessons.length)}.`);
