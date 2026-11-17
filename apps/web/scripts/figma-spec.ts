export {};
// `pnpm figma:spec --version <figmaVersionId> --nodes <id,id> [--depth N] [--max N]`
// Compact, read-only Figma spec for a phase: one line per visible node with box (relative to its frame), fills,
// radius, stroke, effects and text style. GET only; token from FIGMA_TOKEN (never printed), file from FIGMA_FILE_KEY.
const FILE_KEY = process.env.FIGMA_FILE_KEY;
const arg = (name: string) => { const index = process.argv.indexOf(`--${name}`); return index > 0 ? process.argv[index + 1] : undefined; };
const version = arg("version"); const nodes = arg("nodes");
const depth = Number(arg("depth") ?? "6"); const max = Number(arg("max") ?? "400");
const token = process.env.FIGMA_TOKEN;
if (!version || !nodes || !token || !FILE_KEY) throw new Error("Usage: FIGMA_TOKEN=… FIGMA_FILE_KEY=… pnpm figma:spec --version <id> --nodes <id,id> [--depth N] [--max N]");

interface Color { r: number; g: number; b: number; a?: number }
interface Paint { type: string; visible?: boolean; opacity?: number; color?: Color }
interface Effect { type: string; visible?: boolean; radius?: number }
interface FigmaNode {
  id: string; name: string; type: string; visible?: boolean; children?: FigmaNode[];
  absoluteBoundingBox?: { x: number; y: number; width: number; height: number } | null;
  fills?: Paint[]; strokes?: Paint[]; strokeWeight?: number; cornerRadius?: number; rectangleCornerRadii?: number[];
  effects?: Effect[]; opacity?: number; characters?: string;
  style?: { fontFamily?: string; fontWeight?: number; fontSize?: number; lineHeightPx?: number; letterSpacing?: number; textAlignHorizontal?: string };
}
const hex = (paint: Paint) => {
  if (!paint.color) return paint.type.toLowerCase();
  const c = paint.color; const to = (v: number) => Math.round(v * 255).toString(16).padStart(2, "0");
  const alpha = (c.a ?? 1) * (paint.opacity ?? 1);
  return `#${to(c.r)}${to(c.g)}${to(c.b)}${alpha < 1 ? `/${alpha.toFixed(2)}` : ""}`;
};
const url = `https://api.figma.com/v1/files/${FILE_KEY}/nodes?ids=${encodeURIComponent(nodes)}&version=${encodeURIComponent(version)}&geometry=paths`;
const response = await fetch(url, { headers: { "X-Figma-Token": token } });
if (!response.ok) throw new Error(`Figma GET failed: ${String(response.status)}`);
const body = (await response.json()) as { nodes: Record<string, { document: FigmaNode } | null> };
let printed = 0;
for (const [id, entry] of Object.entries(body.nodes)) {
  if (!entry) { console.log(`# ${id}: not found in version ${version}`); continue; }
  const root = entry.document; const origin = root.absoluteBoundingBox ?? { x: 0, y: 0, width: 0, height: 0 };
  console.log(`# ${root.name} (${id}) ${String(Math.round(origin.width))}×${String(Math.round(origin.height))} @ Figma ${version}`);
  const walk = (node: FigmaNode, level: number) => {
    if (node.visible === false || printed >= max) return;
    const box = node.absoluteBoundingBox;
    const parts = [`${"  ".repeat(level)}${node.type[0] ?? "?"} ${node.name.slice(0, 40)}`];
    if (box) parts.push(`[${String(+(box.x - origin.x).toFixed(1))},${String(+(box.y - origin.y).toFixed(1))} ${String(+box.width.toFixed(1))}×${String(+box.height.toFixed(1))}]`);
    const fills = (node.fills ?? []).filter((paint) => paint.visible !== false);
    if (fills.length > 0 && node.type !== "TEXT") parts.push(`fill ${fills.map(hex).join("+")}`);
    if (node.cornerRadius) parts.push(`r${String(node.cornerRadius)}`); else if (node.rectangleCornerRadii) parts.push(`r${node.rectangleCornerRadii.join("/")}`);
    const strokes = (node.strokes ?? []).filter((paint) => paint.visible !== false);
    if (strokes.length > 0) parts.push(`stroke ${String(node.strokeWeight ?? 1)} ${strokes.map(hex).join("+")}`);
    const effects = (node.effects ?? []).filter((effect) => effect.visible !== false);
    if (effects.length > 0) parts.push(`fx ${effects.map((effect) => `${effect.type.toLowerCase()}${effect.radius ? String(effect.radius) : ""}`).join(",")}`);
    if (node.opacity !== undefined && node.opacity < 1) parts.push(`op ${node.opacity.toFixed(2)}`);
    if (node.type === "TEXT" && node.style) {
      const s = node.style;
      parts.push(`text "${(node.characters ?? "").replace(/\s+/g, " ").slice(0, 60)}" ${s.fontFamily ?? ""} ${String(s.fontWeight ?? "")} ${String(s.fontSize ?? "")}/${String(s.lineHeightPx ? +s.lineHeightPx.toFixed(2) : "")} ls${String(+(s.letterSpacing ?? 0).toFixed(2))} ${fills.map(hex).join("+")} ${(s.textAlignHorizontal ?? "").toLowerCase()}`);
    }
    console.log(parts.join(" ")); printed++;
    if (level < depth) for (const child of node.children ?? []) walk(child, level + 1);
  };
  walk(root, 0);
}
if (printed >= max) console.log(`# truncated at ${String(max)} nodes; narrow --nodes or --depth`);
