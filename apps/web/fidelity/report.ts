import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import type { RegionResult } from "./compare.ts";

const escapeHtml = (text: string) => text.replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character] ?? character);

export async function writeFidelityReport(results: readonly RegionResult[], directory: string, provenance: string): Promise<void> {
  await mkdir(directory, { recursive: true });
  const rows = results.map((result) => `<section><h2>${escapeHtml(result.name)} — ${result.pass ? "PASS" : "FAIL"}</h2>
<p>Geometry: ${String(result.geometry.maximumDelta)} CSS px (${result.geometry.pass ? "PASS" : "FAIL"}); solid colour ΔE2000: ${result.color.maximumDeltaE.toFixed(2)} (${result.color.pass ? "PASS" : "FAIL"}); visible area: ${result.visible.areaCssPx.toFixed(1)} CSS px², block ΔE2000 ${result.visible.maximumBlockDeltaE.toFixed(2)} (${result.visible.pass ? "PASS" : "FAIL"}); raw pixelmatch ${result.pixels.percent.toFixed(3)}% (info).</p>
<div class="images">${(["reference", "site", "overlay", "heatmap"] as const).map((key, index) => `<figure><figcaption>${["Figma", "Site", "Overlay 50%", "Heatmap"][index] ?? key}</figcaption><img alt="${escapeHtml(result.name)} ${key}" src="data:image/png;base64,${result.images[key].toString("base64")}"></figure>`).join("")}</div></section>`).join("\n");
  await writeFile(path.join(directory, "index.html"), `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>The Tower fidelity report</title><style>body{font-family:system-ui;margin:2rem}section{margin-block:2rem}.images{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1rem}figure{margin:0}img{max-width:100%;image-rendering:pixelated}figcaption{font-weight:600}</style><h1>The Tower fidelity report</h1><p>${escapeHtml(provenance)}</p><p>Perceptual limits: geometry ≤ 2 CSS px; solid colour ΔE2000 ≤ 2; visible differences (ΔE2000 <p>Limits: geometry ≤ 1 CSS px; color ≤ 2/255 per channel; differing pixels ≤ 0.5% per region; pixelmatch threshold 0.1.</p>gt; 3 outside a 2 CSS px shift envelope, 1 px erosion) ≤ 12 CSS px²; 16 CSS px block mean ΔE2000 ≤ 4. Red in the heatmap = visible difference.</p>${rows}</html>\n`);
  await writeFile(path.join(directory, "results.json"), `${JSON.stringify({ provenance, results: results.map(({ name, pass, geometry, color, visible, pixels }) => ({ name, pass, geometry, color, visible, pixels })) }, null, 2)}\n`);
}
