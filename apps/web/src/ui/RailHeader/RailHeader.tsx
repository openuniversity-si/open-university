import { ChevronRightIcon } from "@/ui/icons/icons";
import styles from "./RailHeader.module.css";

interface RailHeaderProps {
  readonly id: string;
  readonly children: string;
}

/** RailHeader 21:128. The chevron is ornamental: v1 has no author/list destination (§13.4). */
export function RailHeader({ id, children }: RailHeaderProps) {
  return <h2 id={id} className={styles.header} data-testid={`rail-header-${id}`} data-title={children}><span>{children}</span><ChevronRightIcon className={styles.icon} /></h2>;
}
