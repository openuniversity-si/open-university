"use client";

import { errorTitle, homeTitle } from "@/site/domain/reader-copy.ts";
import { EmptyCatalog } from "@/ui/EmptyCatalog/EmptyCatalog";
import { PrimaryCTA } from "@/ui/PrimaryCTA/PrimaryCTA";
import styles from "./status.module.css";

/** D6: render errors show "Something went wrong" with the PrimaryCTA "Home" inside the normal shell. */
export default function ErrorPage() {
  return (
    <div className={styles.page}>
      <EmptyCatalog headingLevel="h1" title={errorTitle} body={null} action={<PrimaryCTA href="/">{homeTitle}</PrimaryCTA>} />
    </div>
  );
}
