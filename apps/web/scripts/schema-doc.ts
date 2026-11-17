import { readFile, writeFile } from "node:fs/promises";
import { SCHEMA_DOC_PATH, renderSchemaDoc, schemaDocProblem } from "../src/catalog/domain/schema/doc.ts";

// pnpm schema:generate writes docs/catalog/schema.md from the zod schema; pnpm schema:check (gate) fails when it is stale.
const target = new URL(`../${SCHEMA_DOC_PATH}`, import.meta.url);
const check = process.argv.includes("--check");

if (check) {
  const problem = schemaDocProblem(await readFile(target, "utf8").catch(() => null));
  if (problem) {
    console.error(`schema:check: ${problem}`);
    process.exit(1);
  }
} else {
  await writeFile(target, renderSchemaDoc());
}
console.log(`schema:${check ? "check" : "generate"}: ${SCHEMA_DOC_PATH} is current.`);
