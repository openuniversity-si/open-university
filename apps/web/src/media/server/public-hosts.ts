import { MEDIA_PUBLIC_HOST, mediaPublicHost, mediaPublicHosts, registerMediaHosts } from "../domain/types.ts";
import { isR2PublicBridge } from "./r2-host.ts";

registerMediaHosts({
  acceptsOverride: (host) => isR2PublicBridge(host),
});

export { MEDIA_PUBLIC_HOST, mediaPublicHost, mediaPublicHosts };
