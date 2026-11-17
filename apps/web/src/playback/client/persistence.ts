import { sendProgress } from "../../progress/client/client.ts";
import type { CompletionHandoff } from "./completion.ts";

/** Decision 4: authenticated persistence of a completion; throws so the pending record is kept on failure. */
export const completionPersistence: CompletionHandoff = {
  async markComplete({ courseSlug, lessonSlug }) {
    if (!await sendProgress({ courseSlug, lessonSlug, completed: true })) throw new Error("Completion not saved");
  },
};
