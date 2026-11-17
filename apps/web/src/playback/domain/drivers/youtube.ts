import { invalid } from "../../../kernel/errors.ts";
import { playlistIdOf, youtubeIdSchema } from "../../../catalog/domain/youtube-identity.ts";
import type { SourceDriver } from "../../ports/source-driver.ts";

export { playlistIdOf, youtubeIdSchema };

const noEmbedOrigins = { scriptSrc: [], frameSrc: [], mediaSrc: [], imgSrc: [], connectSrc: [] } as const;

export const youtubeSourceDriver: SourceDriver = {
  provider: "youtube",
  cspDomains: noEmbedOrigins,
  validateSource(input) {
    if (input.provider !== "youtube") return ["provider"];
    return youtubeIdSchema.safeParse(input.videoId).success ? [] : ["videoId"];
  },
  toPlaybackDescriptor(input) {
    if (input.provider !== "youtube" || !youtubeIdSchema.safeParse(input.videoId).success) throw invalid("Invalid YouTube source.");
    return { kind: "youtube", videoId: input.videoId };
  },
};
