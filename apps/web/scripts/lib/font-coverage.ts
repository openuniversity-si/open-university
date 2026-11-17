import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { brotliDecompressSync } from "node:zlib";

/** UIntBase128 (WOFF2 §4.1): returns [value, next offset]. */
function base128(bytes: Uint8Array, offset: number): [number, number] {
  let value = 0;
  for (let index = 0; index < 5; index += 1) {
    const byte = bytes[offset + index] ?? 0;
    value = value * 128 + (byte & 0x7f);
    if ((byte & 0x80) === 0) return [value, offset + index + 1];
  }
  throw new Error("Invalid UIntBase128.");
}

/** The raw `cmap` table of a single-font WOFF2 file. */
function woff2Cmap(bytes: Uint8Array): DataView {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (view.getUint32(0) !== 0x774f4632) throw new Error("Not a WOFF2 file.");
  const numTables = view.getUint16(12);
  const compressedSize = view.getUint32(20);
  let offset = 48;
  const tables: { cmap: boolean; length: number }[] = [];
  for (let index = 0; index < numTables; index += 1) {
    const flags = bytes[offset] ?? 0;
    offset += 1;
    const known = flags & 0x3f;
    if (known === 63) offset += 4;
    const transform = flags >> 6;
    let length: number;
    [length, offset] = base128(bytes, offset);
    // glyf (10) and loca (11) are transformed by version 0; every other table by a non-zero version.
    if ((known === 10 || known === 11) ? transform === 0 : transform !== 0) [length, offset] = base128(bytes, offset);
    tables.push({ cmap: known === 0, length });
  }
  const data = brotliDecompressSync(bytes.subarray(offset, offset + compressedSize));
  let start = 0;
  for (const table of tables) {
    if (table.cmap) return new DataView(data.buffer, data.byteOffset + start, table.length);
    start += table.length;
  }
  throw new Error("The font has no cmap table.");
}

/** Code points the font maps to a real glyph (Unicode cmap subtables, formats 4 and 12). */
export function woff2Codepoints(bytes: Uint8Array): Set<number> {
  const cmap = woff2Cmap(bytes);
  const points = new Set<number>();
  for (let record = 0; record < cmap.getUint16(2); record += 1) {
    const platform = cmap.getUint16(4 + record * 8);
    const encoding = cmap.getUint16(6 + record * 8);
    if (!(platform === 0 || (platform === 3 && (encoding === 1 || encoding === 10)))) continue;
    const table = cmap.getUint32(8 + record * 8);
    const format = cmap.getUint16(table);
    if (format === 12) {
      for (let group = 0; group < cmap.getUint32(table + 12); group += 1) {
        const at = table + 16 + group * 12;
        for (let point = cmap.getUint32(at); point <= cmap.getUint32(at + 4); point += 1) points.add(point);
      }
    } else if (format === 4) {
      const segments = cmap.getUint16(table + 6) / 2;
      const ends = table + 14;
      const starts = ends + segments * 2 + 2;
      const deltas = starts + segments * 2;
      const ranges = deltas + segments * 2;
      for (let segment = 0; segment < segments; segment += 1) {
        const rangeAt = ranges + segment * 2;
        const rangeOffset = cmap.getUint16(rangeAt);
        for (let point = cmap.getUint16(starts + segment * 2); point <= cmap.getUint16(ends + segment * 2) && point !== 0xffff; point += 1) {
          const glyph = rangeOffset === 0 ? point : cmap.getUint16(rangeAt + rangeOffset + (point - cmap.getUint16(starts + segment * 2)) * 2);
          if (glyph !== 0 && (glyph + cmap.getInt16(deltas + segment * 2)) % 65536 !== 0) points.add(point);
        }
      }
    }
  }
  return points;
}

function files(directory: string, keep: (file: string) => boolean): string[] {
  return readdirSync(directory, { withFileTypes: true, recursive: true })
    .filter((entry) => entry.isFile() && keep(entry.name))
    .map((entry) => path.join(entry.parentPath, entry.name));
}
function strings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(strings);
  return value && typeof value === "object" ? Object.values(value).flatMap(strings) : [];
}

/**
 * Every printable character of the site's static text, with one file that uses it: the baked current release and
 * the source (comments stripped) under `src/`. Over-inclusive on purpose (identifiers and CSS too).
 */
export function staticTextCharacters(root: string): Map<string, string> {
  const found = new Map<string, string>();
  const add = (text: string, file: string) => { for (const character of text) if (character >= " " && !found.has(character)) found.set(character, path.relative(root, file)); };
  const releaseFile = path.join(root, "src/catalog/domain/generated/release.json");
  add(strings(JSON.parse(readFileSync(releaseFile, "utf8"))).join(""), releaseFile);
  for (const file of files(path.join(root, "src"), (name) => /\.tsx?$/.test(name) && !name.includes(".test."))) {
    add(readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|\s)\/\/.*$/gm, "$1"), file);
  }
  return found;
}
