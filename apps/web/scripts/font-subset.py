"""Builds public/fonts/Inter.woff2: the pinned Inter variable TTF (wght 100-900) subset to scripts/fonts/inter-unicodes.txt.

Run from apps/web: `pnpm fonts:subset` (needs fonttools and brotli: `pip install --user fonttools brotli`).
The source is downloaded from the URL in public/fonts/manifest.json and checked against its sha256.
"""
import hashlib
import json
import pathlib
import re
import tempfile
import urllib.request

from fontTools import subset
from fontTools.ttLib import TTFont

root = pathlib.Path(__file__).resolve().parent.parent
fonts = root / "public" / "fonts"
manifest_path = fonts / "manifest.json"
manifest = json.loads(manifest_path.read_text())
inter = next(entry for entry in manifest if entry["family"] == "inter")
unicodes = [re.sub(r"#.*", "", line).strip() for line in (root / "scripts" / "fonts" / "inter-unicodes.txt").read_text().splitlines()]
unicodes = [line for line in unicodes if line]

with tempfile.TemporaryDirectory() as directory:
    source = pathlib.Path(directory) / "Inter-roman.var.ttf"
    with urllib.request.urlopen(inter["source"], timeout=60) as response:
        source.write_bytes(response.read())
    if hashlib.sha256(source.read_bytes()).hexdigest() != inter["sourceSha256"]:
        raise SystemExit("Inter source sha256 changed; refusing to subset.")
    output = fonts / "Inter.woff2"
    # Default layout features (kern, calt, locl, ...) and hinting are kept, so text renders as with the full TTF.
    subset.main([str(source), f"--unicodes={','.join(unicodes)}", "--flavor=woff2", f"--output-file={output}"])

font = TTFont(output)
axis = font["fvar"].axes[0]
if (axis.axisTag, axis.minValue, axis.maxValue) != ("wght", 100.0, 900.0):
    raise SystemExit("The wght 100-900 axis was not preserved.")
inter.update({"file": output.name, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "subset": "scripts/fonts/inter-unicodes.txt"})
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
print(f"{output.name}: {output.stat().st_size} bytes, {len(font.getGlyphOrder())} glyphs")
