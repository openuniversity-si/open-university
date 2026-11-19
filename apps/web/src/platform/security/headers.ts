/**
 * Response headers every page and file of the site carries (SSDF PW.9, docs/security/SECURE-DEFAULTS.md).
 * The site is HTTPS only behind CloudFront, never framed (the CSP's frame-ancestors 'none' only reports while the
 * policy is report-only, so X-Frame-Options enforces it), and sends only its origin to other sites.
 */
export const SECURITY_HEADERS: readonly { readonly key: string; readonly value: string }[] = [
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
];
