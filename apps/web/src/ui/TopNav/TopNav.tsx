"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useState } from "react";
import { useAuth } from "@/identity/client/AuthProvider";
import { useShellCopy } from "@/config/client/shell-copy.tsx";
import { accountForTemplate, authorsTitle, brandHomeLabel, fill, homeTitle, primaryNavLabel, signInLabel, universitiesTitle } from "@/site/domain/reader-copy.ts";
import { AccountMenuOverlay } from "@/ui/identity/AccountMenu";
import { ChevronLeftIcon } from "@/ui/icons/icons";
import { TowerMark } from "@/ui/TowerMark/TowerMark";
import { topNavContext } from "./context";
import styles from "./TopNav.module.css";

/** Fixed navigation with shared account actions on Home, Course and Player. */
export function TopNav({ labels }: { readonly labels: { readonly home: string; readonly course: string } }) {
  const copy = useShellCopy();
  const tabs = [
    { id: "home", href: "/", label: copy.homeTitle ?? homeTitle },
    { id: "universities", href: "/universities", label: copy.universitiesTitle ?? universitiesTitle },
    { id: "authors", href: "/authors", label: copy.authorsTitle ?? authorsTitle },
  ] as const;
  const { context, tab, back } = topNavContext(usePathname(), labels);
  const { viewer, busy, startSignIn, signOut } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = useCallback(() => { setMenuOpen(false); }, []);
  return (
    <header className={styles.root} data-testid="tower-topnav" data-context={context} data-fidelity-fixed="">
      <div className="tower-glass tower-glass--liquid tower-header-glass" aria-hidden="true" data-testid="tower-header-glass" />
      <div className={styles.left} data-testid="tower-topnav-left">
        {back ? (
          <Link className={styles.back} href={back.href} aria-label={back.label} data-testid="tower-topnav-back">
            <ChevronLeftIcon className={styles.chevron} />
          </Link>
        ) : null}
        <Link className={styles.brand} href="/" aria-label={copy.brandHomeLabel ?? brandHomeLabel} data-testid="tower-topnav-brand">
          <TowerMark className={styles.mark} />
        </Link>
        <nav className={styles.nav} aria-label={copy.primaryNavLabel ?? primaryNavLabel} data-context={context}>
          {tabs.map((item) => (
            <Link key={item.id} className={[styles.item, "t-ui-nav"].join(" ")} href={item.href} aria-current={tab === item.id ? "page" : undefined} data-testid={`tower-topnav-${item.id}`}>
              {item.label}
              <span className={styles.underline} aria-hidden="true" />
            </Link>
          ))}
        </nav>
      </div>
      {viewer ? <button className={styles.avatar} type="button" aria-label={fill(copy.accountForTemplate ?? accountForTemplate, { name: viewer.name })} aria-haspopup="menu" aria-expanded={menuOpen}
        data-testid="tower-topnav-avatar" onClick={(event) => { event.currentTarget.focus({ preventScroll: true }); setMenuOpen(true); }}>
        <span data-testid="tower-avatar-circle">{Array.from(viewer.name.trim())[0]?.toUpperCase() ?? "?"}</span>
      </button> : <button className={[styles.session, "t-ui-label-14-medium"].join(" ")} type="button" disabled={busy}
        onClick={() => { void startSignIn(); }} data-testid="tower-topnav-sign-in">
        {copy.signInLabel ?? signInLabel}
      </button>}
      {viewer && menuOpen ? <AccountMenuOverlay name={viewer.name} onClose={closeMenu} onSignOut={() => { void signOut().then((success) => { if (success) closeMenu(); }); }} /> : null}
    </header>
  );
}
