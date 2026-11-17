import { readFile } from "node:fs/promises";

// `pnpm fidelity:summary`: pass count plus the 5 worst regions from the last `pnpm fidelity` run (fidelity/report/results.json).
interface Row { name: string; pass: boolean; geometry: { maximumDelta: number }; color: { maximumDeltaE: number }; visible: { areaCssPx: number; maximumBlockDeltaE: number } }
const { provenance, results } = JSON.parse(await readFile("fidelity/report/results.json", "utf8")) as { provenance: string; results: Row[] };
const passed = results.filter((row) => row.pass).length;
console.log(`${provenance}\nfidelity: ${String(passed)}/${String(results.length)} regions pass.`);
const score = (row: Row) => Math.max(row.geometry.maximumDelta / 2, row.color.maximumDeltaE / 2, row.visible.areaCssPx / 12, row.visible.maximumBlockDeltaE / 4);
for (const row of [...results].sort((a, b) => score(b) - score(a)).slice(0, 5)) {
  console.log(`${row.pass ? "pass" : "FAIL"} ${row.name}: geometry ${String(row.geometry.maximumDelta)}px, solid ΔE ${row.color.maximumDeltaE.toFixed(2)}, visible ${row.visible.areaCssPx.toFixed(1)}px², block ΔE ${row.visible.maximumBlockDeltaE.toFixed(2)}`);
}
