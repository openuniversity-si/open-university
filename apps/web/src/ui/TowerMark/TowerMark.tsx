interface TowerMarkProps {
  readonly className?: string;
}

/**
 * Brand/TowerMark 20:80. The visible layer is Saturn 675:15176, the provisional PNG
 * approved 2026-10-22 (master 112×60). Header and footer sizes live in shell.css.
 */
export function TowerMark({ className }: TowerMarkProps) {
  return (
    <picture>
      <img className={className} src="/brand/logo.png" alt="" width={112} height={60} data-testid="tower-mark" />
    </picture>
  );
}
