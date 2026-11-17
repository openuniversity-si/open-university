export interface Violation {
  rule: string;
  file: string;
  line: number;
  detail: string;
}
interface Edge { file: string; line: number; specifier: string; target?: string }
interface Context {
  root: string;
  files: Set<string>;
  edges: Edge[];
  toolingEdges: Edge[];
  add(rule: string, file: string, line: number, detail: string): void;
}
export interface ArchitectureRule { id: string; check(context: Context): void }
export const architectureHalves: { readonly site: readonly string[]; readonly factory: readonly string[] };
export const defaultRules: ArchitectureRule[];
export const muxTombstones: string[];
export function checkArchitecture(options?: { root?: string; rules?: ArchitectureRule[] }): Violation[];
