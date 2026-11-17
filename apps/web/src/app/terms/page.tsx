import type { Metadata } from "next";
import { toMetadata } from "@/app/to-metadata";
import { staticPageMetadata } from "@/site/domain/metadata";
import { siteData } from "@/site/server/site-data";
import { LegalPage } from "@/ui/LegalPage/LegalPage";

export const metadata: Metadata = toMetadata(staticPageMetadata("/terms"));

export default function TermsPage() {
  const data = siteData();
  return <LegalPage page={data.pages.terms} updated={data.legal.updated} />;
}
