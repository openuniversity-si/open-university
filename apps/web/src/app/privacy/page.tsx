import type { Metadata } from "next";
import { toMetadata } from "@/app/to-metadata";
import { staticPageMetadata } from "@/site/domain/metadata";
import { siteData } from "@/site/server/site-data";
import { LegalPage } from "@/ui/LegalPage/LegalPage";

export const metadata: Metadata = toMetadata(staticPageMetadata("/privacy"));

export default function PrivacyPage() {
  const data = siteData();
  return <LegalPage page={data.pages.privacy} updated={data.legal.updated} />;
}
