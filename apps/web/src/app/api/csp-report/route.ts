import { LIMITS } from "../../../kernel/limits.ts";
import { logStructured } from "../../../platform/observability/logger.ts";
import { summarizeCspReports } from "@/platform/security/csp";

export const dynamic = "force-dynamic";

/** CSP violation sink (F09, enforced since 19/11): logs which directive blocked which origin; never stores the payload. */
export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  if (body.length <= LIMITS.cspReportBytes) {
    for (const line of summarizeCspReports(body)) logStructured("warn", "CSP_VIOLATION", { line });
  }
  return new Response(null, { status: 204 });
}
