import { cookies, draftMode } from "next/headers";
import { currentEnv } from "@/kernel/env.ts";
import { PREVIEW_COOKIE, handlePreviewRequest } from "@/catalog/server/preview-route.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return handlePreviewRequest(request, {
    secret: currentEnv().TOWER_ADMIN_MEDIA_SECRET,
    now: () => new Date(),
    async enable(token, maxAge) {
      (await draftMode()).enable();
      (await cookies()).set(PREVIEW_COOKIE, token, { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge });
    },
    async disable() {
      (await draftMode()).disable();
      (await cookies()).delete(PREVIEW_COOKIE);
    },
  });
}
