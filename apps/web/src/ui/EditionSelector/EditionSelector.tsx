"use client";

import { useRef, type KeyboardEvent } from "react";
import { editionLabel } from "@/site/domain/reader-copy.ts";
import { useEditionScope } from "./EditionScope";
import { editionPanelId, editionTabId } from "./ids";
import styles from "./EditionSelector.module.css";

export interface EditionTab { readonly slug: string; readonly label: string }


/** Arrow keys move and select (automatic activation), Home/End jump; wraps like a toolbar of tabs. */
export function nextTab(key: string, index: number, count: number): number | null {
  if (key === "ArrowRight" || key === "ArrowDown") return (index + 1) % count;
  if (key === "ArrowLeft" || key === "ArrowUp") return (index - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

/**
 * EditionSelector 575:2023: one 88 px tab per edition, newest first, the selected one lit. Only rendered for a course with
 * more than one edition (Editions=1 is empty in the design). A tablist labelled "Edition" that controls the lesson list.
 */
export function EditionSelector({ editions }: { readonly editions: readonly EditionTab[] }) {
  const { selected, select } = useEditionScope();
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const target = nextTab(event.key, index, editions.length);
    const edition = target === null ? undefined : editions[target];
    if (target === null || !edition) return;
    event.preventDefault();
    select(edition.slug);
    tabs.current[target]?.focus();
  };
  return (
    <div className={`tower-glass tower-glass--clear ${styles.bar ?? ""}`} role="tablist" aria-label={editionLabel} data-testid="edition-selector">
      {editions.map((edition, index) => {
        const active = edition.slug === selected;
        return (
          <button key={edition.slug} ref={(node) => { tabs.current[index] = node; }} type="button" role="tab" id={editionTabId(edition.slug)} className={styles.tab}
            aria-selected={active} aria-controls={editionPanelId(edition.slug)} tabIndex={active ? 0 : -1} data-edition={edition.slug}
            onClick={() => { select(edition.slug); }} onKeyDown={(event) => { onKeyDown(event, index); }}>
            {edition.label}
          </button>
        );
      })}
    </div>
  );
}
