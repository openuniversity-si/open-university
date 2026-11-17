import { AppError } from "../../kernel/errors.ts";

/** An object-store operation failed. The message names the operation, not a vendor. */
export class StorageError extends AppError {
  constructor(message: string) { super("upstream_failed", message); this.name = "StorageError"; }
}
