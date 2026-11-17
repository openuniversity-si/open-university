import { LIMITS } from "../../../kernel/limits.ts";
import { logStructured } from "../../../platform/observability/logger.ts";
import { summarizeCspReports } from "@/platform/security/csp";

export const dynamic = "force-dynamic";

/** Report-only CSP sink (F09): logs which directive blocked which origin; never stores the payload. */
export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  if (body.length <= LIMITS.cspReportBytes) {
    for (const line of summarizeCspReports(body)) logStructured("warn", "CSP_REPORT_ONLY", { line });
  }
  return new Response(null, { status: 204 });
}
