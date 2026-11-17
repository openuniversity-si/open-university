import type { Metadata } from "next";
import { CACHE } from "@/kernel/cache.ts";
import { readPreviewPage } from "@/app/catalog-preview";
import { imageCredits } from "@/catalog/domain/credits";
import { toMetadata } from "@/app/to-metadata";
import { staticPageMetadata } from "@/site/domain/metadata";
import { siteData } from "@/site/server/site-data";
import { CreditsList } from "@/ui/CreditsList/CreditsList";
import { LegalPage } from "@/ui/LegalPage/LegalPage";
import { CREDITS_NOTE } from "@/ui/showcase/shelf-sentences.ts";

/** Image credits of the active release (src/catalog/domain/credits.ts); the only place cover credits are shown. */
// A day: every release activation purges it on demand (invalidateCatalog), so the window is only a safety net.
export const revalidate = 86_400 satisfies typeof CACHE.directorySeconds;

export const metadata: Metadata = toMetadata(staticPageMetadata("/credits"));

export default async function CreditsPage() {
  const credits = imageCredits(await readPreviewPage({ kind: "release" }));
  return <LegalPage page={{ ...siteData().pages.credits, lead: CREDITS_NOTE }} card={<CreditsList credits={credits} />} />;
}
