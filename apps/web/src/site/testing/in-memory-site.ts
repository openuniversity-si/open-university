import { upcastSiteData } from "../domain/site-data.ts";
import type { SiteDataStorePort } from "../ports/data.ts";
import type { SiteBench } from "./site-contract.ts";
import { siteFixtureV2 } from "./site-fixture.ts";

/** A validated copy of site data. There is no write path and no site table. */
export function createInMemorySiteData(raw: unknown = siteFixtureV2): SiteBench {
  let data = structuredClone(upcastSiteData(raw));
  let closed = false;
  const port: SiteDataStorePort = {
    read() { return Promise.resolve(structuredClone(data)); },
  };
  return {
    port,
    reset() {
      if (closed) throw new Error("The in-memory site store is closed.");
      data = structuredClone(upcastSiteData(siteFixtureV2));
      return Promise.resolve();
    },
    dispose() { closed = true; return Promise.resolve(); },
    load(next) {
      return Promise.resolve().then(() => {
        if (closed) throw new Error("The in-memory site store is closed.");
        data = structuredClone(upcastSiteData(next));
      });
    },
  };
}
