"use client";

import { createContext, useCallback, useContext, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";

/** The query parameter that names a non-default edition (shareable; the server always renders the default one). */
export const EDITION_PARAM = "edition";

/** Back/forward may restore another `?edition=`. */
function subscribeToHistory(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  return () => { window.removeEventListener("popstate", onChange); };
}

interface Scope { readonly slugs: readonly string[]; readonly selected: string; readonly select: (slug: string) => void }
const EditionContext = createContext<Scope | null>(null);

/** `?edition=<slug>` when it names one of `slugs` other than the default (first); otherwise null. */
export function editionFromSearch(search: string, slugs: readonly string[]): string | null {
  const slug = new URLSearchParams(search).get(EDITION_PARAM);
  return slug !== null && slugs.includes(slug) && slug !== slugs[0] ? slug : null;
}

/** The URL after choosing `slug`: the parameter is dropped for the default edition, so the plain course URL stays canonical. */
export function urlWithEdition(href: string, slug: string, slugs: readonly string[]): string {
  const url = new URL(href);
  if (slug === slugs[0]) url.searchParams.delete(EDITION_PARAM);
  else url.searchParams.set(EDITION_PARAM, slug);
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * The selected edition of one course page (ADR-21). The server renders the default edition (position 1) with every other
 * edition's panes hidden, so the page needs no search params (no flash, no layout shift). On the client the choice is read
 * from and written to `?edition=` with history.replaceState: no navigation, no new history entry.
 */
export function EditionScope({ slugs, children }: { readonly slugs: readonly string[]; readonly children: ReactNode }) {
  // The server snapshot is null (default edition); after hydration the URL's edition, until the viewer picks one.
  const fromUrl = useSyncExternalStore(subscribeToHistory, () => editionFromSearch(window.location.search, slugs), () => null);
  const [chosen, setChosen] = useState<string | null>(null);
  const selected = chosen ?? fromUrl ?? slugs[0] ?? "";
  const select = useCallback((slug: string) => {
    setChosen(slug);
    window.history.replaceState(window.history.state, "", urlWithEdition(window.location.href, slug, slugs));
  }, [slugs]);
  const scope = useMemo(() => ({ slugs, selected, select }), [slugs, selected, select]);
  return <EditionContext.Provider value={scope}>{children}</EditionContext.Provider>;
}

export function useEditionScope(): Scope {
  const scope = useContext(EditionContext);
  if (!scope) throw new Error("EditionSelector and EditionPane need an EditionScope.");
  return scope;
}

/** Content of one edition: present in the HTML, hidden unless its edition is selected. `inline` for a span inside text. */
export function EditionPane({ slug, inline = false, children, ...rest }: { readonly slug: string; readonly inline?: boolean; readonly children: ReactNode; readonly id?: string; readonly role?: "tabpanel"; readonly "aria-labelledby"?: string }) {
  const { selected } = useEditionScope();
  const Tag = inline ? "span" : "div";
  return <Tag {...rest} hidden={selected !== slug} data-edition={slug}>{children}</Tag>;
}
