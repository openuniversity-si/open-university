import "server-only";
import { cookies, draftMode } from "next/headers";
import { cache } from "react";
import { readPageCatalog, type PageRead } from "@/catalog/server/page-reads";
import { PREVIEW_COOKIE } from "@/catalog/server/preview-token";

/** Draft mode and the preview cookie, read in the route. Catalog modules do not call `draftMode` or `cookies`. */
export const requestPreview = cache(async (): Promise<{ readonly preview: boolean; readonly cookie?: string }> => {
  if (!(await draftMode()).isEnabled) return { preview: false };
  return { preview: true, cookie: (await cookies()).get(PREVIEW_COOKIE)?.value };
});

/** The page catalog, including a draft when this request is in preview. */
export async function readPreviewPage(selection: PageRead = { kind: "release" }) {
  const { preview, cookie } = await requestPreview();
  return readPageCatalog(selection, preview, cookie);
}
