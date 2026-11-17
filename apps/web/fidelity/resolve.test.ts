import { describe, expect, it } from "vitest";
import { FIDELITY_FRAMES, type FidelityFrame } from "./frames.ts";
import type { LocalReferenceSet } from "./references/active.ts";
import { framesForPhase, resolveFrame } from "./resolve.ts";

const set: LocalReferenceSet = {
  set: { id: "7", figmaFileKey: "file", figmaVersionId: "123", createdAt: "2026-10-08T16:00:00.000Z", isActive: true, note: null },
  images: [{ nodeId: "29:399", screenKey: "home-mobile-390--29-399@2x", viewport: "390@2x", blobUrl: "https://store/x.png", sha256: "a".repeat(64), width: 780, height: 1688 }],
  nodes: [{ rootNodeId: "29:399", nodeId: "I29:525;21:37", name: "Left", x: 20, y: 14, width: 16.8, height: 28 }],
  files: { "home-mobile-390--29-399@2x": ".fidelity-cache/images/a.png" },
};
const region = { name: "TopNav brand", figmaNodeId: "I29:525;21:37", selector: "[data-testid=tower-topnav-brand]", colorSamples: [{ x: 1, y: 1 }] };
const frame: FidelityFrame = { id: "home-390-dpr2", phase: "F05", figmaNodeId: "29:399", capture: "viewport", route: "/", viewport: 390, dpr: 2, regions: [region] };

describe("fidelity frame resolution against the active set", () => {
  it("binds the reference image and region geometry from tower_tooling", () => {
    const resolved = resolveFrame(frame, set);
    expect(resolved.referenceFile).toBe(".fidelity-cache/images/a.png");
    expect(resolved.regions[0]?.referenceBox).toEqual({ x: 20, y: 14, width: 16.8, height: 28 });
  });

  it("compares only the poster box, excluding the static card's top padding", () => {
    const resolved = resolveFrame({ ...frame, regions: [{ ...region, posterBox: true }] }, set);
    expect(resolved.regions[0]?.referenceBox).toEqual({ x: 20, y: 16, width: 16.8, height: 26 });
  });

  it("fails loudly when the active set lacks the image, the node, or regions", () => {
    expect(() => resolveFrame({ ...frame, dpr: 1 }, set)).toThrow(/no 390@1x reference for node 29:399/);
    expect(() => resolveFrame({ ...frame, regions: [{ ...region, figmaNodeId: "9:9" }] }, set)).toThrow(/node 9:9 \(TopNav brand\) is not under 29:399/);
    expect(() => resolveFrame({ ...frame, regions: [] }, set)).toThrow(/no comparison regions/);
  });

  it("filters by phase and rejects duplicate ids or malformed phases", () => {
    expect(framesForPhase([frame, { ...frame, id: "other", phase: "F06" }], "F05").map((item) => item.id)).toEqual(["home-390-dpr2"]);
    expect(framesForPhase([frame, { ...frame, id: "later", phase: "F04", gates: ["F05"] }], "F05").map((item) => item.id)).toEqual(["home-390-dpr2", "later"]);
    expect(framesForPhase(FIDELITY_FRAMES, "F09").map((item) => item.id)).toEqual(framesForPhase(FIDELITY_FRAMES, "F08").filter((item) => item.id.startsWith("player-")).map((item) => item.id));
    expect(() => framesForPhase([frame, frame], undefined)).toThrow(/Duplicate/);
    expect(() => framesForPhase([frame], "5")).toThrow(/--phase FNN/);
  });

  it("registers both shell captures at every reference viewport and DPR", () => {
    const frames = framesForPhase(FIDELITY_FRAMES, "F05");
    for (const viewport of [390, 1366, 1920]) {
      for (const dpr of [1, 2]) {
        const pair = frames.filter((item) => item.viewport === viewport && item.dpr === dpr);
        expect(pair.map((item) => item.capture).sort()).toEqual(["fullPage", "viewport"]);
        expect(pair.flatMap((item) => item.regions.map((entry) => entry.name))).toEqual(expect.arrayContaining(["TopNav", "Footer"]));
      }
    }
  });
});
