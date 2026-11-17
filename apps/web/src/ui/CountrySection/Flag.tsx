import type { FlagGeometry } from "./flags";

/** A true-colour flag at its official ratio; the height comes from CSS and the width follows it (never stretched). */
export function Flag({ id, flag, className }: { readonly id: string; readonly flag: FlagGeometry; readonly className?: string | undefined }) {
  return (
    <svg className={className} viewBox={`0 0 ${String(flag.width)} ${String(flag.height)}`} style={{ aspectRatio: `${String(flag.width)} / ${String(flag.height)}` }} preserveAspectRatio="xMidYMid meet" overflow="hidden" aria-hidden="true" focusable="false" data-flag={id}>
      {flag.shapes.map((shape, index) => {
        const paint = { fill: shape.fill, stroke: shape.stroke, strokeWidth: shape.strokeWidth };
        if (shape.kind === "rect") return <rect key={index} x={shape.x} y={shape.y} width={shape.width} height={shape.height} {...paint} />;
        if (shape.kind === "circle") return <circle key={index} cx={shape.cx} cy={shape.cy} r={shape.r} {...paint} />;
        return <path key={index} d={shape.d} {...paint} />;
      })}
    </svg>
  );
}
