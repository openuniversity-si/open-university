import sharp from "sharp";
import type { FigmaClient, FigmaFile, FigmaNode } from "./figma.ts";

/** A miniature production page: one screen with scroll content, one external mock, one state board. */
export function fakePage(shift = 0): FigmaNode {
  const frame = (id: string, name: string, x: number, y: number, width: number, height: number, children: FigmaNode[] = []): FigmaNode =>
    ({ id, name, type: "FRAME", absoluteBoundingBox: { x, y, width, height }, children });
  return {
    id: "18:3", name: "Home Desired", type: "CANVAS", children: [
      frame("29:399", "Home — Mobile 390", 0, 1500, 39, 84, [
        frame("29:400", "Scroll content", 0, 1500, 39, 120, [frame("29:401", "Billboard", 0, 1500 + shift, 39, 62)]),
        { ...frame("29:524", "BottomNav spacer", 0, 1572, 39, 7), visible: false },
        frame("29:525", "TopNav (fixed)", 0, 1500, 39, 6, [frame("I29:525;21:37", "Left", 2, 1501, 2, 3)]),
      ]),
      frame("154:18453", "Google external — Home — Desktop 1920 — account chooser", 100, 0, 192, 108),
      { id: "31:734", name: "Label/① Home", type: "TEXT", absoluteBoundingBox: { x: 0, y: -40, width: 25, height: 3 } },
      frame("293:14604", "Estados — aprovados (Daniel 2026-10-08)", 0, 1770, 160, 380, [
        frame("293:14607", "A · Carregando", 6, 1792, 147, 77, [frame("293:14610", "Canvas", 6, 1800, 147, 70)]),
        frame("293:14637", "B · Vazio", 6, 1875, 147, 83, [frame("293:14640", "Canvas", 6, 1880, 147, 76)]),
      ]),
    ],
  };
}

export const solidPng = (width: number, height: number, red: number): Promise<Buffer> =>
  sharp({ create: { width, height, channels: 4, background: { r: red, g: 30, b: 40, alpha: 1 } } }).png().toBuffer();

/** In-process stand-in for the Figma REST client: renders solid PNGs at the node's size × scale. */
export function fakeFigma(version: string, page: FigmaNode, red = 10): FigmaClient & { readonly renders: { count: number } } {
  const index = new Map<string, FigmaNode>();
  const walk = (node: FigmaNode) => { index.set(node.id, node); node.children?.forEach(walk); };
  walk(page);
  const renders = { count: 0 };
  return {
    renders,
    file: (): Promise<FigmaFile> => Promise.resolve({ version, lastModified: "2026-10-08T15:51:56Z", document: { id: "0:0", name: "Document", type: "DOCUMENT", children: [page] } }),
    nodes: (_key, ids) => Promise.resolve(new Map(ids.map((id) => [id, page]))),
    renderUrls: (_key, ids, scale) => Promise.resolve(new Map(ids.map((id) => [id, `render://${id}@${String(scale)}`]))),
    async download(url) {
      const match = /^render:\/\/(.+)@([12])$/.exec(url);
      const node = match?.[1] ? index.get(match[1]) : undefined;
      if (!match || !node?.absoluteBoundingBox) throw new Error("Unknown render URL.");
      renders.count++;
      const scale = Number(match[2]);
      return solidPng(Math.round(node.absoluteBoundingBox.width * scale), Math.round(node.absoluteBoundingBox.height * scale), red);
    },
  };
}
