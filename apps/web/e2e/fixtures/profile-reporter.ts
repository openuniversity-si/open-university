import { writeFileSync } from "node:fs";
import type { FullResult, Reporter, TestCase, TestResult, TestStep } from "@playwright/test/reporter";

/** Opt in with TOWER_E2E_PROFILE; sums can overlap (fixture/hook parents include their children). */
export default class ProfileReporter implements Reporter {
  private readonly steps = new Map<string, { count: number; milliseconds: number }>();

  onStepEnd(test: TestCase, _result: TestResult, step: TestStep) {
    const operation = step.category === "pw:api" ? step.title.split("(")[0] ?? step.title : `${step.category}: ${step.title}`;
    const key = `${test.parent.project()?.name ?? "unknown"}: ${operation}`;
    const entry = this.steps.get(key) ?? { count: 0, milliseconds: 0 };
    entry.count += 1;
    entry.milliseconds += step.duration;
    this.steps.set(key, entry);
  }

  onEnd(result: FullResult) {
    if (process.env.TOWER_E2E_PROFILE) {
      writeFileSync(process.env.TOWER_E2E_PROFILE, JSON.stringify({
        duration: result.duration,
        operations: Object.fromEntries([...this.steps].sort((a, b) => b[1].milliseconds - a[1].milliseconds)),
      }, null, 2));
    }
  }
}
