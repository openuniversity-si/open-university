import localFont from "next/font/local";

/**
 * Inter variable (wght 100–900) subset to the site's characters (scripts/font-subset.py,
 * scripts/fonts/inter-unicodes.txt): one preloaded ~37 KB woff2 instead of the 296 KB TTF.
 * The metric-matched Arial fallback keeps the swap from shifting layout.
 */
export const towerInter = localFont({
  src: "../../public/fonts/Inter.woff2",
  variable: "--tower-font-inter-face",
  weight: "100 900",
  style: "normal",
  display: "swap",
  preload: true,
  adjustFontFallback: "Arial",
});
