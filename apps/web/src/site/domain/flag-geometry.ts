import { invalid } from "../../kernel/errors.ts";

export interface FlagShape {
  readonly kind: "rect" | "path" | "circle";
  readonly fill?: string;
  readonly stroke?: string;
  readonly strokeWidth?: number;
  readonly x?: number; readonly y?: number; readonly width?: number; readonly height?: number;
  readonly d?: string;
  readonly cx?: number; readonly cy?: number; readonly r?: number;
}
export interface FlagGeometry { readonly width: number; readonly height: number; readonly shapes: readonly FlagShape[] }

function finite(value: number | undefined, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw invalid(`${path} must be a finite number.`);
  return value;
}

/** Accepts only the three shapes the flag component draws. No arbitrary SVG attributes. */
export function validateFlagGeometry(flag: FlagGeometry, path = "flag"): FlagGeometry {
  if (!(flag.width > 0) || !(flag.height > 0)) throw invalid(`${path} needs positive dimensions.`);
  flag.shapes.forEach((shape, index) => {
    const at = `${path}.shapes.${String(index)}`;
    if (shape.strokeWidth !== undefined && !(shape.strokeWidth >= 0)) throw invalid(`${at}.strokeWidth must be non-negative.`);
    if (shape.kind === "rect") {
      for (const key of ["x", "y", "width", "height"] as const) finite(shape[key], `${at}.${key}`);
      if (!((shape.width ?? 0) > 0) || !((shape.height ?? 0) > 0)) throw invalid(`${at} needs a positive box.`);
    } else if (shape.kind === "circle") {
      for (const key of ["cx", "cy", "r"] as const) finite(shape[key], `${at}.${key}`);
      if (!((shape.r ?? 0) > 0)) throw invalid(`${at}.r must be positive.`);
    } else if (typeof shape.d !== "string" || shape.d.trim() === "") throw invalid(`${at}.d must be a non-empty path.`);
  });
  return flag;
}
