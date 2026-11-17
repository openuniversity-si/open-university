import Link from "next/link";
import type { ReactNode } from "react";
import { ChevronRightIcon, PlayIcon } from "@/ui/icons/icons";
import styles from "./PrimaryCTA.module.css";

interface PrimaryCTAProps {
  readonly href: string;
  readonly children: ReactNode;
  /** Icon/Play before the label (Start/Resume); navigation CTAs such as "Home" omit it. */
  readonly play?: boolean;
  readonly disabled?: boolean;
  readonly kind?: "primary" | "secondary";
  readonly arrow?: boolean;
  readonly prefetch?: boolean;
}

/** C1 Clear glass pill; secondary navigation keeps its quiet text treatment. */
export function PrimaryCTA({ href, children, play = false, disabled = false, kind = "primary", arrow = false, prefetch }: PrimaryCTAProps) {
  const secondary = kind === "secondary";
  const className = [styles.cta, secondary ? styles.secondary : "tower-glass tower-glass--clear tower-cta"].join(" ");
  const testId = secondary ? "tower-secondary-cta" : "tower-primary-cta";
  const content = <>{play ? <PlayIcon className={styles.icon} /> : null}<span className={styles.label} data-label={typeof children === "string" ? children : undefined}>{children}</span>{arrow ? <ChevronRightIcon className={styles.arrow} /> : null}</>;
  if (disabled) {
    return <span className={className} role="link" aria-disabled="true" data-testid={testId}>{content}</span>;
  }
  return (
    <Link className={className} href={href} prefetch={prefetch} data-testid={testId}>
      {content}
    </Link>
  );
}
