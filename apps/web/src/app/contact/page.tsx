import type { Metadata } from "next";
import { toMetadata } from "@/app/to-metadata";
import { staticPageMetadata } from "@/site/domain/metadata";
import { LEGAL_EMAIL, siteData } from "@/site/server/site-data";
import { LegalEmailCard, LegalPage } from "@/ui/LegalPage/LegalPage";
import { PrimaryCTA } from "@/ui/PrimaryCTA/PrimaryCTA";

export const metadata: Metadata = toMetadata(staticPageMetadata("/contact"));

export default function ContactPage() {
  const contact = siteData().pages.contact;
  const card = <LegalEmailCard label={contact.cardLabel} email={LEGAL_EMAIL} cta={<PrimaryCTA href={`mailto:${LEGAL_EMAIL}`}>{contact.cta}</PrimaryCTA>} />;
  return <LegalPage page={contact} card={card} variant="contact" />;
}
