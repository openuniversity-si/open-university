import { expect, it } from "vitest";
import { ancestorsOf, parentOf, type HierarchyNode } from "./hierarchy.ts";

// Verifies: REQ-contract-inv-h3
const nodes: HierarchyNode[] = [
  { kind: "institution", id: "school" }, { kind: "area", id: "subject" },
  { kind: "subarea", id: "branch", areaId: "subject" },
  { kind: "course", id: "intro", institutionId: "school", areaId: "subject", subareaId: "branch" },
  { kind: "course", id: "direct", institutionId: "school", areaId: "subject" },
  { kind: "course", id: "draft", institutionId: "school" },
  { kind: "lesson", id: "first", courseId: "intro" },
];
it.each([
  [0, []], [1, []], [2, ["subject"]], [3, ["branch", "subject"]],
  [4, ["subject"]], [5, []], [6, ["intro", "branch", "subject"]],
] as const)("INV-H3: parent and ancestors of node %i follow taxonomy", (index, expected) => {
  const node = nodes[index];
  if (!node) throw new Error("fixture");
  expect(parentOf(node)?.id).toBe(expected[0]);
  expect(ancestorsOf(node, nodes).map((entry) => entry.id)).toEqual(expected);
});
it("D-014: provenance reaches the institution and never lends a taxonomy parent", () => {
  const course = nodes[3];
  if (!course) throw new Error("fixture");
  expect(ancestorsOf(course, nodes, "provenance")).toEqual([{ kind: "institution", id: "school" }]);
  expect(ancestorsOf(course, nodes)).not.toContainEqual({ kind: "institution", id: "school" });
});
