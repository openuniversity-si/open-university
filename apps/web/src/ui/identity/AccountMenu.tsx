"use client";

import { useEffect, useRef } from "react";
import { accountMenuLabel, closeAccountMenuLabel, signOutLabel } from "@/site/domain/reader-copy.ts";
import { OverlayLayer } from "@/ui/OverlayLayer/OverlayLayer";
import styles from "./AccountMenu.module.css";

interface AccountMenuProps {
  readonly name: string;
  readonly onSignOut?: () => void;
}

/** Presentational Regular glass panel. F10 supplies the account actions. */
export function AccountMenu({ name, onSignOut }: AccountMenuProps) {
  return (
    <div className={["tower-glass tower-glass--regular tower-account-menu", styles.panel].join(" ")} role="menu" aria-label={accountMenuLabel} data-testid="tower-account-menu">
      <p className={styles.name} role="presentation">{name}</p>
      <button className={styles["sign-out"]} type="button" role="menuitem" onClick={onSignOut}>{signOutLabel}</button>
    </div>
  );
}

interface AccountMenuOverlayProps extends AccountMenuProps {
  readonly onClose?: () => void;
}

function AccountMenuContent({ name, onSignOut, onClose }: AccountMenuOverlayProps) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    const item = root.current?.querySelector<HTMLButtonElement>('[role="menuitem"]');
    root.current?.focus({ preventScroll: true });
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose?.(); }
      if (event.key === "Tab") { event.preventDefault(); item?.focus(); }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      if (previous instanceof HTMLElement) previous.focus({ preventScroll: true });
    };
  }, [onClose]);
  return (
    <div className={styles.overlay} ref={root} tabIndex={-1} data-testid="tower-account-overlay">
      <button className={styles.outside} type="button" tabIndex={-1} aria-label={closeAccountMenuLabel} onClick={onClose} />
      <div className={styles.veil} aria-hidden="true" />
      <AccountMenu name={name} onSignOut={onSignOut} />
    </div>
  );
}

export function AccountMenuOverlay(props: AccountMenuOverlayProps) {
  return <OverlayLayer><AccountMenuContent {...props} /></OverlayLayer>;
}
