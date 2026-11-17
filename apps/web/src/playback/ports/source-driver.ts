export type SourceInput =
  | { readonly provider: "youtube"; readonly videoId: string }
  | { readonly provider: "institutional-url"; readonly url: string };

export type PlaybackDescriptor =
  | { readonly kind: "youtube"; readonly videoId: string }
  | { readonly kind: "external-link"; readonly url: string };

export interface CspDomains {
  readonly scriptSrc: readonly string[];
  readonly frameSrc: readonly string[];
  readonly mediaSrc: readonly string[];
  readonly imgSrc: readonly string[];
  readonly connectSrc: readonly string[];
}

export interface SourceDriver {
  readonly provider: SourceInput["provider"];
  readonly cspDomains: CspDomains;
  validateSource(input: SourceInput): readonly string[];
  /** Revalidates and throws AppError invalid when the input does not match this driver. */
  toPlaybackDescriptor(input: SourceInput): PlaybackDescriptor;
}
