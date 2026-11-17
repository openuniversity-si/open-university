import "server-only";
import raw from "../../../content/site/site-data.v2.json";
import { installSiteData, parseSiteData, type SiteDataV2 } from "../domain/site-data.ts";
import type { SiteDataStorePort } from "../ports/data.ts";

const data = parseSiteData(raw);
installSiteData(data);

/** The approved site manifesto. Importing this module installs it for metadata. */
export function siteData(): SiteDataV2 { return data; }
export function siteDataStore(): SiteDataStorePort {
  return { read: () => Promise.resolve(siteData()) };
}
export const LEGAL_EMAIL: string = data.legal.publicContactEmails[0];
