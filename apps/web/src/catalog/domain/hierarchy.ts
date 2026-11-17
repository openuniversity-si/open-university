/** INV-H3: taxonomy parents are independent of provenance. Cover art does not walk these parents (D-031). */
export type NodeKind = "institution" | "area" | "subarea" | "course" | "lesson";
export type HierarchyNode =
  | { readonly kind: "institution" | "area"; readonly id: string }
  | { readonly kind: "subarea"; readonly id: string; readonly areaId: string }
  | { readonly kind: "course"; readonly id: string; readonly institutionId: string; readonly areaId?: string | null; readonly subareaId?: string | null }
  | { readonly kind: "lesson"; readonly id: string; readonly courseId: string };
export interface NodeRef { readonly kind: NodeKind; readonly id: string }
export function parentOf(node: HierarchyNode, axis: "taxonomy" | "provenance" = "taxonomy"): NodeRef | undefined {
  if (axis === "provenance") return node.kind === "course" ? { kind: "institution", id: node.institutionId } : undefined;
  if (node.kind === "lesson") return { kind: "course", id: node.courseId };
  if (node.kind === "subarea") return { kind: "area", id: node.areaId };
  if (node.kind === "course") {
    if (node.subareaId) return { kind: "subarea", id: node.subareaId };
    if (node.areaId) return { kind: "area", id: node.areaId };
  }
  return undefined;
}
/** Nearest first. Missing snapshot nodes stop traversal rather than inventing ancestry. */
export function ancestorsOf(node: HierarchyNode, nodes: readonly HierarchyNode[], axis: "taxonomy" | "provenance" = "taxonomy"): NodeRef[] {
  const result: NodeRef[] = [];
  let parent = parentOf(node, axis);
  while (parent) {
    result.push(parent);
    const stored = nodes.find((entry) => entry.kind === parent?.kind && entry.id === parent.id);
    parent = stored ? parentOf(stored, axis) : undefined;
  }
  return result;
}
