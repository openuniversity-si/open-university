import type { ReferenceNode } from "./repository.ts";

/** The design spec's Figma file key: private, read from `FIGMA_FILE_KEY` and never written in the repository. */
export function specFileKey(env: Readonly<Record<string, string | undefined>> = process.env): string {
  const key = env.FIGMA_FILE_KEY?.trim();
  if (!key) throw new Error("FIGMA_FILE_KEY is not set; it names the design spec's Figma file.");
  return key;
}
/** The approved production screens page (`18:3`); every other page is tokens, components, spec or suggestions. */
export const PRODUCTION_PAGE_IDS = ["18:3"] as const;
/** Pages that must never feed references, even if listed by mistake. */
export const IGNORED_PAGE = /suggestion|backup|archiv|out of scope|⛔/i;
/** Mock of Google's own account chooser: external UI, never implemented or compared. */
const EXTERNAL_FRAME = /^Google external\b/;
/** The approved state board on 18:3; its per-state "Canvas" frames are exported. */
const STATE_BOARD = /^(?:States|Estados)\b/;
export const REFERENCE_SCALES = [1, 2] as const;

export interface FigmaBox {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface FigmaNode {
  readonly id: string;
  readonly name: string;
  readonly type: string;
  readonly visible?: boolean;
  readonly absoluteBoundingBox?: FigmaBox | null;
  readonly children?: readonly FigmaNode[];
}

export interface FigmaFile {
  readonly version: string;
  readonly lastModified: string;
  readonly document: FigmaNode;
}

export type ExportKind = "screen" | "scroll" | "state";

/** One exported root: a production screen, its full "Scroll content", or a state canvas. */
export interface ExportRoot {
  readonly nodeId: string;
  readonly kind: ExportKind;
  readonly baseKey: string;
  /** Width of the top-level frame this root belongs to (390, 1366, 1920; 1600 for the state board). */
  readonly frameWidth: number;
}

export interface PlannedImage {
  readonly root: ExportRoot;
  readonly scale: 1 | 2;
  readonly screenKey: string;
  readonly viewport: string;
}

export const slug = (value: string): string => value.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase()
  .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 96).replace(/-+$/, "");

const nodeKey = (nodeId: string) => nodeId.replace(/[^0-9]+/g, "-");
const visibleChildren = (node: FigmaNode) => (node.children ?? []).filter((child) => child.visible !== false);
const box = (node: FigmaNode): FigmaBox => {
  if (!node.absoluteBoundingBox) throw new Error(`Figma node ${node.id} has no bounding box.`);
  return node.absoluteBoundingBox;
};

/** Pick the production export roots from full-depth reads of the production pages. */
export function planExportRoots(pages: readonly FigmaNode[]): ExportRoot[] {
  const roots: ExportRoot[] = [];
  for (const page of pages) {
    if (IGNORED_PAGE.test(page.name)) throw new Error(`Page ${page.id} (${page.name}) is not a production page.`);
    for (const frame of visibleChildren(page)) {
      if (frame.type !== "FRAME" || EXTERNAL_FRAME.test(frame.name)) continue;
      const frameWidth = Math.round(box(frame).width);
      if (STATE_BOARD.test(frame.name)) {
        for (const section of visibleChildren(frame)) {
          const canvas = visibleChildren(section).find((child) => child.name === "Canvas");
          if (!canvas) continue;
          const letter = /^([A-Z])\b/.exec(section.name)?.[1]?.toLowerCase();
          roots.push({ nodeId: canvas.id, kind: "state", baseKey: `state-${letter ?? slug(section.name)}--${nodeKey(canvas.id)}`, frameWidth });
        }
        continue;
      }
      const name = slug(frame.name);
      roots.push({ nodeId: frame.id, kind: "screen", baseKey: `${name}--${nodeKey(frame.id)}`, frameWidth });
      const scroll = visibleChildren(frame).find((child) => child.name === "Scroll content");
      if (scroll) roots.push({ nodeId: scroll.id, kind: "scroll", baseKey: `${name}-scroll--${nodeKey(scroll.id)}`, frameWidth });
    }
  }
  const keys = new Set(roots.map((root) => root.baseKey));
  if (keys.size !== roots.length) throw new Error("Duplicate reference screen keys.");
  if (!roots.some((root) => root.kind === "screen")) throw new Error("No production screen found on the production pages.");
  return roots;
}

export function planImages(roots: readonly ExportRoot[]): PlannedImage[] {
  return roots.flatMap((root) => REFERENCE_SCALES.map((scale) => ({
    root, scale, screenKey: `${root.baseKey}@${String(scale)}x`, viewport: `${String(root.frameWidth)}@${String(scale)}x`,
  })));
}

/** geometry.json equivalent: every visible node under `root`, relative to the root's top-left corner. */
export function rootGeometry(root: FigmaNode): ReferenceNode[] {
  const origin = box(root);
  const nodes: ReferenceNode[] = [];
  const walk = (node: FigmaNode) => {
    if (node.visible === false) return;
    if (node.absoluteBoundingBox) {
      const { x, y, width, height } = node.absoluteBoundingBox;
      nodes.push({ rootNodeId: root.id, nodeId: node.id, name: node.name, x: x - origin.x, y: y - origin.y, width, height });
    }
    for (const child of node.children ?? []) walk(child);
  };
  walk(root);
  return nodes;
}

/** Width and height from a PNG's IHDR chunk; rejects anything that is not a PNG. */
export function pngSize(bytes: Buffer): { readonly width: number; readonly height: number } {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (bytes.length < 24 || !bytes.subarray(0, 8).equals(signature) || bytes.toString("latin1", 12, 16) !== "IHDR") throw new Error("Not a PNG image.");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

type Fetch = (url: string, init?: RequestInit) => Promise<Response>;

/** Read-only Figma REST client (GET on api.figma.com/v1 only); retries 429/5xx and never logs the token. */
export function createFigmaClient(token: string, fetchImpl: Fetch = fetch, wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))) {
  async function getJson<T>(path: string, query: Readonly<Record<string, string>> = {}): Promise<T> {
    const url = new URL(`https://api.figma.com/v1/${path}`);
    for (const [key, value] of Object.entries(query)) url.searchParams.set(key, value);
    for (let attempt = 1; ; attempt++) {
      const response = await fetchImpl(url.href, { method: "GET", headers: { "X-Figma-Token": token } });
      if (response.ok) return await response.json() as T;
      if ((response.status === 429 || response.status >= 500) && attempt < 6) {
        const retryAfter = Number(response.headers.get("retry-after"));
        await wait(Number.isFinite(retryAfter) && retryAfter > 0 ? Math.min(retryAfter, 120) * 1000 : 2000 * attempt);
        continue;
      }
      throw new Error(`Figma GET /v1/${path} failed with HTTP ${String(response.status)}.`);
    }
  }
  return {
    file: (fileKey: string) => getJson<FigmaFile>(`files/${fileKey}`, { depth: "1" }),
    async nodes(fileKey: string, ids: readonly string[], version: string): Promise<Map<string, FigmaNode>> {
      const result = await getJson<{ nodes: Record<string, { document: FigmaNode } | null> }>(`files/${fileKey}/nodes`, { ids: ids.join(","), version });
      return new Map(ids.map((id) => {
        const node = result.nodes[id]?.document;
        if (!node) throw new Error(`Figma node ${id} is missing at version ${version}.`);
        return [id, node];
      }));
    },
    async renderUrls(fileKey: string, ids: readonly string[], scale: 1 | 2, version: string): Promise<Map<string, string>> {
      const result = await getJson<{ err: string | null; images: Record<string, string | null> }>(`images/${fileKey}`, {
        ids: ids.join(","), format: "png", scale: String(scale), version, use_absolute_bounds: "true",
      });
      if (result.err) throw new Error(`Figma render failed: ${result.err}`);
      return new Map(ids.map((id) => {
        const url = result.images[id];
        if (!url) throw new Error(`Figma returned no render for ${id} at ${String(scale)}x.`);
        return [id, url];
      }));
    },
    /** Rendered PNGs live on Figma's CDN; the token is never sent there. */
    async download(url: string): Promise<Buffer> {
      for (let attempt = 1; ; attempt++) {
        const response = await fetchImpl(url, { method: "GET" });
        if (response.ok) return Buffer.from(await response.arrayBuffer());
        if (attempt >= 4) throw new Error(`Render download failed with HTTP ${String(response.status)}.`);
        await wait(1000 * attempt);
      }
    },
  };
}

export type FigmaClient = ReturnType<typeof createFigmaClient>;
