import type { SiteDataV2 } from "../domain/site-data.ts";

/** Read-only editorial site data. There is no site table and no write API. */
export interface SiteDataStorePort {
  read(): Promise<SiteDataV2>;
}
