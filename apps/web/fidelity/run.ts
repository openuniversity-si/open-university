import { readFile } from "node:fs/promises";
import { compareRegion, type GeometryBox, type RegionResult } from "./compare.ts";
import { COURSE_NAME_ROW_DELTA, FIDELITY_FRAMES } from "./frames.ts";
import { exceptionMaskNodes, hasException, kickerWrapDelta, shiftedByKicker } from "./exceptions.ts";
import { referenceMediaLayers } from "./media.ts";
import { readLocalSet } from "./references/active.ts";
import { writeFidelityReport } from "./report.ts";
import { framesForPhase, resolveFrame } from "./resolve.ts";
import { runFidelitySelftest } from "./selftest.ts";

// `pnpm fidelity [--phase FNN]`: compares Playwright captures with the active reference set
// that `pnpm fidelity:references` verified into the local cache.
const args = process.argv.slice(2);
const phase = args[0] === "--phase" && args.length === 2 ? args[1] : undefined;
if (args.length > 0 && phase === undefined) throw new Error("Usage: pnpm fidelity [--phase FNN]");
const set = await readLocalSet();
const frames = framesForPhase(FIDELITY_FRAMES, phase);
const provenance = `Active reference set ${set.set.id}: Figma ${set.set.figmaFileKey} version ${set.set.figmaVersionId} (${String(set.images.length)} images).`;
console.log(`fidelity: ${provenance} ${String(frames.length)} product frame(s) registered${phase ? ` for ${phase}` : ""}.`);
if (frames.length === 0) {
  if (phase) throw new Error(`No fidelity frames are registered for ${phase}.`);
  await runFidelitySelftest();
} else {
  const results: RegionResult[] = [];
  for (const frame of frames) {
    const resolved = resolveFrame(frame, set);
    const siteBoxes = JSON.parse(await readFile(`.reports/fidelity/${frame.id}.geometry.json`, "utf8")) as Record<string, GeometryBox>;
    const layers = referenceMediaLayers(frame, set);
    const mediaBoxes = layers.length ? JSON.parse(await readFile(`.reports/fidelity/${frame.id}.media.json`, "utf8")) as Record<string, GeometryBox> : {};
    const headerReference = resolved.regions.find((entry) => entry.region.name === "LessonHeader")?.referenceBox;
    const kickerDelta = kickerWrapDelta(frame.phase, frame.viewport, headerReference, siteBoxes["LessonHeader"]);
    for (const { region, referenceBox: fullReferenceBox } of resolved.regions) {
      const fullSiteBox = siteBoxes[region.name];
      if (!fullSiteBox) throw new Error(`Missing DOM geometry for ${frame.id}/${region.name}.`);
      // Exception kicker-full-course-name (exceptions.ts): compare LessonHeader from its Title down, offset by the approved wrap.
      let referenceBox = fullReferenceBox, siteBox = fullSiteBox, geometryShift = shiftedByKicker(region.name) ? kickerDelta : 0;
      if (region.name === "LessonHeader" && hasException(frame.phase, region.name, "kicker-full-course-name")) {
        const title = set.nodes.find((entry) => entry.rootNodeId === frame.figmaNodeId && entry.name === "Title" && entry.y > fullReferenceBox.y && entry.y < fullReferenceBox.y + fullReferenceBox.height);
        if (!title) throw new Error(`Missing locked Title in ${frame.id}/LessonHeader.`);
        const top = title.y - fullReferenceBox.y;
        referenceBox = { ...fullReferenceBox, y: fullReferenceBox.y + top, height: fullReferenceBox.height - top };
        siteBox = { ...fullSiteBox, y: fullSiteBox.y + top + kickerDelta, height: fullSiteBox.height - top - kickerDelta };
        geometryShift = 0;
      }
      const relative = (box: GeometryBox, crop: GeometryBox): GeometryBox => ({ ...box, x: box.x - crop.x, y: box.y - crop.y });
      const overlaps = (a: GeometryBox, b: GeometryBox) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
      const mediaMasks = layers.filter((layer) => overlaps(layer.box, referenceBox)).map((layer) => {
        const box = mediaBoxes[layer.nodeId];
        if (!box) throw new Error(`Missing media geometry for ${frame.id}/${layer.nodeId}.`);
        // The image element's full rectangle includes antialiased clip pixels and translucent
        // chrome over the art. The companion checks their radius/hairline/tint without masking.
        return { reference: relative(layer.box, referenceBox), site: relative(box, siteBox), radius: 0 };
      });
      const stateMasks = [...(region.signedOutMasks ?? []).map((id) => {
        const node = set.nodes.find((entry) => entry.rootNodeId === frame.figmaNodeId && entry.nodeId === id);
        if (!node) throw new Error(`Missing D1 mask ${frame.id}/${id}.`);
        return relative(node, referenceBox);
      }), ...exceptionMaskNodes(frame.phase, region.name, set.nodes.filter((entry) => entry.rootNodeId === frame.figmaNodeId), region.figmaNodeId).map((node) => relative(node, referenceBox))];
      const labelDelta = (region.precedingLabelRows ?? 0) * COURSE_NAME_ROW_DELTA[frame.viewport === 390 ? "mobile" : "desktop"];
      results.push(await compareRegion({ name: `${frame.id}/${region.name}`, reference: resolved.referenceFile, site: `.reports/fidelity/${frame.id}.png`, referenceBox, siteBox, siteGeometryBox: region.name === "LessonHeader" && kickerDelta ? { ...siteBox, y: siteBox.y - kickerDelta } : { ...siteBox, y: siteBox.y - labelDelta - geometryShift }, dpr: frame.dpr, referenceBackground: frame.referenceBackground, colorSamples: region.colorSamples, clipToFrame: region.clipToFrame, mediaMasks, stateMasks, ...(mediaMasks.length ? { mediaChromeSite: `.reports/fidelity/${frame.id}.chrome.png` } : {}) }));
    }
  }
  await writeFidelityReport(results, "fidelity/report", provenance);
  const failed = results.filter((result) => !result.pass);
  console.log(`fidelity: ${String(results.length - failed.length)}/${String(results.length)} regions pass.${failed.length > 0 ? ` FAIL (first 5): ${failed.slice(0, 5).map((result) => result.name).join(", ")}; details: pnpm fidelity:summary` : ""}`);
  process.exitCode = failed.length === 0 ? 0 : 1;
}
