import { institutionalUrlDriver } from "../domain/drivers/institutional-url.ts";
import { youtubeSourceDriver } from "../domain/drivers/youtube.ts";
import type { CspDomains, SourceDriver } from "../ports/source-driver.ts";
import { embedContentSources } from "./oembed-resolver.ts";

const keys = ["scriptSrc", "frameSrc", "mediaSrc", "imgSrc", "connectSrc"] as const;

/** Ordered union of declared origins. Later drivers do not reorder an origin already recorded. */
export function unionCsp(drivers: readonly SourceDriver[]): CspDomains {
  const result: { [Key in keyof CspDomains]: string[] } = { scriptSrc: [], frameSrc: [], mediaSrc: [], imgSrc: [], connectSrc: [] };
  for (const key of keys) {
    const seen = new Set<string>();
    for (const driver of drivers) {
      for (const origin of driver.cspDomains[key]) {
        if (seen.has(origin)) continue;
        seen.add(origin);
        result[key].push(origin);
      }
    }
  }
  return result;
}

/** YouTube is the live embed. The institutional driver is a link and contributes no frame, script or media origin. */
export function playbackDrivers(institutionalHosts: readonly string[] = []): readonly SourceDriver[] {
  return [{ ...youtubeSourceDriver, cspDomains: embedContentSources() }, institutionalUrlDriver(institutionalHosts)];
}

/** Provider id stored on `lesson_videos`. The only registered embed driver supplies it. */
export function catalogVideoProvider(): string {
  return youtubeSourceDriver.provider;
}

export function playbackContentSources(institutionalHosts: readonly string[] = []): CspDomains {
  return unionCsp(playbackDrivers(institutionalHosts));
}
