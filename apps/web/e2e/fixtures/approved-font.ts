import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * The approved Inter (public/fonts/Inter.woff2, the only web font) also installed as the test browsers' local "Inter".
 * `next/font` falls back to a metric-adjusted local("Arial") that this Linux lacks, so the stack reaches whatever
 * "Inter" (or sans-serif) the system has: whenever the web font arrived after first paint, the swap shifted the layout
 * (Chromium desktop, lazy-posters). Test browsers get a fontconfig whose only "Inter" is the approved file, so fallback
 * and web font render alike. Chromium cannot load WOFF2 as a system font, so the local copy is the same font unpacked
 * from WOFF2 to sfnt by fontTools (the dependency of `pnpm fonts:subset`). No @font-face is added (the type identity
 * guard stays as it is) and nothing changes for visitors.
 */
export const APPROVED_FONT = fileURLToPath(new URL("../../public/fonts/Inter.woff2", import.meta.url));
export const APPROVED_FONT_SHA256 = createHash("sha256").update(readFileSync(APPROVED_FONT)).digest("hex");
export const APPROVED_FONT_DIR = join(tmpdir(), `open-university-e2e-fonts-${APPROVED_FONT_SHA256.slice(0, 16)}`);
/** The local copy: the approved WOFF2 unpacked, named after the approved file's SHA-256. */
export const APPROVED_LOCAL_FONT = join(APPROVED_FONT_DIR, "fonts", `Inter-${APPROVED_FONT_SHA256}.ttf`);

const xml = (text: string): string => text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const UNPACK = "import sys\nfrom fontTools.ttLib import TTFont\nfont = TTFont(sys.argv[1])\nfont.flavor = None\nfont.save(sys.argv[2])\n";
/** `TOWER_PYTHON` when set, otherwise python3 on PATH. It needs fontTools with WOFF2 support (`pip install "fonttools[woff]"`). */
function fontPython(): string {
  return process.env.TOWER_PYTHON ?? "python3";
}

/** Writes (idempotently, atomically) the local font and fontconfig file and returns the path for FONTCONFIG_FILE. */
export function approvedFontConfig(): string {
  const file = join(APPROVED_FONT_DIR, "fonts.conf");
  mkdirSync(join(APPROVED_FONT_DIR, "fonts"), { recursive: true });
  if (!existsSync(APPROVED_LOCAL_FONT)) {
    const unpacked = `${APPROVED_LOCAL_FONT}.${String(process.pid)}`;
    const python = fontPython();
    const unpack = () => execFileSync(python, ["-E", "-P", "-c", UNPACK, APPROVED_FONT, unpacked], { stdio: "pipe" });
    try {
      unpack();
    } catch (error) {
      throw new Error(`e2e needs fontTools to install the approved Inter locally: ${python} -m pip install "fonttools[woff]" (or set TOWER_PYTHON)`, { cause: error });
    }
    renameSync(unpacked, APPROVED_LOCAL_FONT);
  }
  // Every other "Inter" the system offers is hidden by path (fontconfig cannot reject a family yet keep one file of it).
  const env = { ...process.env };
  delete env.FONTCONFIG_FILE;
  const systemInter = execFileSync("fc-list", ["-f", "%{file}\\n", "Inter"], { encoding: "utf8", env }).split("\n").filter(Boolean);
  const conf = `<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>
  <dir>${xml(join(APPROVED_FONT_DIR, "fonts"))}</dir>
  <cachedir>${xml(join(APPROVED_FONT_DIR, "cache"))}</cachedir>
  <selectfont>
    <rejectfont>${systemInter.map((path) => `<glob>${xml(path)}</glob>`).join("")}</rejectfont>
  </selectfont>
</fontconfig>
`;
  const tmpConf = `${file}.${String(process.pid)}`;
  writeFileSync(tmpConf, conf);
  renameSync(tmpConf, file);
  return file;
}
