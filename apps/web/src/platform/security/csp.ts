/**
 * Report-only CSP (F09): observe what the Player needs before enforcing anything.
 * Production plays the embed. Frame, script and thumbnail origins come from the playback driver.
 */
export const CSP_REPORT_PATH = "/api/csp-report";

/** Origins supplied by a caller. The platform does not import a playback driver to discover them. */
export interface CspSources {
  readonly scriptSrc?: readonly string[];
  readonly frameSrc?: readonly string[];
  readonly mediaSrc?: readonly string[];
  readonly imgSrc?: readonly string[];
  readonly connectSrc?: readonly string[];
}

function directive(name: string, values: readonly string[]): string {
  const body = values.filter((value) => value !== "").join(" ");
  return body === "" ? name : `${name} ${body}`;
}

export function reportOnlyContentSecurityPolicy(mediaHosts: readonly string[], sources: CspSources = {}): string {
  const media = mediaHosts.map((host) => `https://${host}`);
  return [
    "default-src 'self'",
    directive("script-src", ["'self'", "'unsafe-inline'", ...(sources.scriptSrc ?? [])]),
    "style-src 'self' 'unsafe-inline'",
    directive("img-src", ["'self'", "data:", "blob:", ...media, ...(sources.imgSrc ?? [])]),
    "font-src 'self'",
    directive("media-src", ["'self'", "blob:", ...(sources.mediaSrc ?? [])]),
    directive("connect-src", ["'self'", ...(sources.connectSrc ?? [])]),
    directive("frame-src", sources.frameSrc ?? []),
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    `report-uri ${CSP_REPORT_PATH}`,
    "report-to csp",
  ].join("; ");
}

/** `directive → origin` per report, from either the Reporting API array or a legacy `csp-report` body. */
export function summarizeCspReports(body: string): string[] {
  let parsed: unknown;
  try { parsed = JSON.parse(body); } catch { return []; }
  const reports = Array.isArray(parsed) ? parsed.map((entry: unknown) => (typeof entry === "object" && entry !== null && "body" in entry ? entry.body : null)) : [(parsed as { "csp-report"?: unknown })["csp-report"]];
  return reports.slice(0, 20).flatMap((report) => {
    if (typeof report !== "object" || report === null) return [];
    const fields = report as Record<string, unknown>;
    const directive = fields.effectiveDirective ?? fields["effective-directive"] ?? fields["violated-directive"];
    const blocked = fields.blockedURL ?? fields["blocked-uri"];
    if (typeof directive !== "string" || typeof blocked !== "string") return [];
    const origin = URL.canParse(blocked) ? new URL(blocked).origin : blocked.slice(0, 40);
    return [`${directive.slice(0, 40)} → ${origin}`];
  });
}
