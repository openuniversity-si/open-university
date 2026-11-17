"use client";

import { useEffect, useRef, useState } from "react";
import { whenNear } from "./near";

interface LazyPosterProps {
  readonly className: string | undefined;
  readonly src: string;
  readonly width: number;
  readonly height: number;
}

/**
 * Poster below the eager rows/cards (P8): no `src` in the HTML (the cover's placeholder shows), requested when it comes
 * near the viewport (`<picture>` like the eager cards: a plain image, pre-optimized at the origin). `<noscript>` keeps the image without JS; `loading="lazy"` and low priority keep it out of preloads.
 */
export function LazyPoster({ className, src, width, height }: LazyPosterProps) {
  const ref = useRef<HTMLImageElement>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const image = ref.current;
    return image ? whenNear(image, () => { setNear(true); }) : undefined;
  }, []);
  const attributes = { className, width, height, loading: "lazy", decoding: "async", fetchPriority: "low" } as const;
  return (
    <>
      <picture><img ref={ref} {...attributes} alt="" src={near ? src : undefined} data-poster-src={src} /></picture>
      <noscript><picture><img {...attributes} alt="" src={src} /></picture></noscript>
    </>
  );
}
