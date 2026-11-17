/**
 * ADR-02 / §8.1: literal colours and px lengths only live in src/ui/tokens/.
 * Everything else consumes `var(--tower-*)`.
 */
/** @type {import("stylelint").Config} */
const config = {
  extends: ["stylelint-config-standard"],
  ignoreFiles: [".next/**", ".next-test/**", "node_modules/**", "test-results/**", "playwright-report/**"],
  rules: {
    "color-no-hex": true,
    "color-named": "never",
    "function-disallowed-list": ["rgb", "rgba", "hsl", "hsla", "hwb", "lab", "lch", "oklab", "oklch", "color"],
    // Spec 01 breakpoints are the only px values allowed outside the token files.
    "unit-disallowed-list": [["px", "rem", "em", "pt", "pc", "cm", "mm", "in"], { ignoreMediaFeatureNames: { px: ["width"] } }],
    "declaration-property-value-allowed-list": {
      "font-size": ["/^var\\(--tower-/", "inherit"],
      "font-weight": ["/^var\\(--tower-/", "inherit"],
      "letter-spacing": ["/^var\\(--tower-/", "inherit", "normal"],
      "line-height": ["/^var\\(--tower-/", "inherit", "normal"],
    },
  },
  overrides: [
    {
      files: ["src/ui/glass.css"],
      rules: {
        // Keep the locked pack's shared API and Safari-only rendering aliases.
        "selector-class-pattern": "^[a-z][a-z0-9]*(?:-{1,2}[a-z0-9]+)*(?:__[a-z0-9]+(?:-[a-z0-9]+)*)?$",
        "property-no-vendor-prefix": [true, { ignoreProperties: ["-webkit-backdrop-filter", "-webkit-mask", "-webkit-mask-composite"] }],
      },
    },
    {
      files: ["src/ui/tokens/**/*.css"],
      rules: {
        "color-no-hex": null,
        // Preserve literal Figma hex spelling in the deterministic generated file.
        "color-hex-length": null,
        "color-named": null,
        "function-disallowed-list": null,
        "unit-disallowed-list": null,
        "declaration-property-value-allowed-list": null,
      },
    },
  ],
};

export default config;
