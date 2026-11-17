import { CACHE } from "../../kernel/cache.ts";
import { PREVIEW_COOKIE, safePreviewTarget, verifyPreviewToken } from "./preview-token.ts";

export interface PreviewRouteDeps {
  readonly secret: string | undefined;
  readonly now: () => Date;
  /** Turns draft mode on (Next's bypass cookie) and stores the signed token for the pages to verify. */
  readonly enable: (token: string, maxAgeSeconds: number) => Promise<void>;
  readonly disable: () => Promise<void>;
}

const HEADERS = { "Cache-Control": CACHE.responseNoStore, "X-Robots-Tag": "noindex" } as const;
const deny = (status: 400 | 401) => new Response(status === 401 ? "Unauthorized." : "Bad request.", { status, headers: HEADERS });

/**
 * GET /api/catalog/preview?token=…&to=/c/<slug> (public): a valid token turns draft mode on and redirects (307) to a
 * same-site path; anything else is a generic 401 or 400. `?exit=1` leaves preview. ADR-18.
 */
export async function handlePreviewRequest(request: Request, deps: PreviewRouteDeps): Promise<Response> {
  const url = new URL(request.url);
  if (url.searchParams.get("exit") === "1") {
    await deps.disable();
    return new Response(null, { status: 307, headers: { ...HEADERS, Location: new URL("/", url).toString() } });
  }
  const to = safePreviewTarget(url.searchParams.get("to") ?? "/");
  if (to === null) return deny(400);
  const token = url.searchParams.get("token");
  const claims = verifyPreviewToken(deps.secret, token, deps.now());
  if (!claims || token === null) return deny(401);
  await deps.enable(token, Math.max(1, claims.exp - Math.floor(deps.now().getTime() / 1000)));
  return new Response(null, { status: 307, headers: { ...HEADERS, Location: new URL(to, url).toString() } });
}

export { PREVIEW_COOKIE };
