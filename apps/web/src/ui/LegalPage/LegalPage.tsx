import { slugify } from "@/kernel/slug";
import type { ReactNode } from "react";
import { type LegalPageContent, legalSegments } from "@/site/domain/legal";
import styles from "./LegalPage.module.css";

/** Copy with its URLs and email address as underlined links (external ones open in a new tab). */
export function LegalText({ text }: { readonly text: string }) {
  return legalSegments(text).map((segment, index) => {
    if (segment.kind === "text") return segment.text;
    const external = segment.external ? { target: "_blank", rel: "noopener noreferrer" } : {};
    return <a key={index} className={styles.link} href={segment.href} {...external}>{segment.text}</a>;
  });
}

/**
 * ◆ Privacy | Terms | Contact | About (Mobile 390, Desktop 1920): one left column on the Home gutter with
 * kicker, H1, optional "Last updated", lead, optional body paragraphs, an optional card (Contact), the H2
 * sections and an optional action (About). The "about" variant sets the lead and body one step larger.
 */
export function LegalPage({ page, updated, card, action, variant = "legal" }: {
  readonly page: LegalPageContent;
  readonly updated?: string;
  readonly card?: ReactNode;
  readonly action?: ReactNode;
  readonly variant?: "legal" | "contact" | "about";
}) {
  return (
    <article className={styles.page} data-variant={variant} data-testid="tower-legal-page">
      <p className={styles.kicker}>{page.kicker}</p>
      <h1 className={styles.title}>{page.title}</h1>
      {updated ? <p className={styles.updated}>Last updated {updated}</p> : null}
      <p className={styles.lead}><LegalText text={page.lead} /></p>
      {page.body?.map((text) => <p key={text} className={styles.body}><LegalText text={text} /></p>)}
      {page.wink ? <p className={styles.wink}><LegalText text={page.wink} /></p> : null}
      {page.closing ? <p className={styles.closing}><LegalText text={page.closing} /></p> : null}
      {card}
      {page.sections?.map((section) => (
        <section key={section.h} className={styles.section} aria-labelledby={`legal-${slugify(section.h, { fallback: "" })}`}>
          <h2 id={`legal-${slugify(section.h, { fallback: "" })}`} className={styles.heading}>{section.h}</h2>
          {section.p?.map((text) => <p key={text}><LegalText text={text} /></p>)}
          {section.ul ? <ul>{section.ul.map((text) => <li key={text}><LegalText text={text} /></li>)}</ul> : null}
          {section.after?.map((text) => <p key={text}><LegalText text={text} /></p>)}
        </section>
      ))}
      {action ? <div className={styles.action}>{action}</div> : null}
    </article>
  );
}

/** Contact "Email card": EMAIL label, the address and the PrimaryCTA mailto. */
export function LegalEmailCard({ label, email, cta }: { readonly label: string; readonly email: string; readonly cta: ReactNode }) {
  return (
    <div className={styles.card} data-testid="tower-legal-email-card">
      <p className={styles.kicker}>{label}</p>
      <a className={styles.email} href={`mailto:${email}`}>{email}</a>
      {cta}
    </div>
  );
}
