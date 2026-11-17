import "server-only";
import { AppError } from "../../kernel/errors.ts";
import type { MailerPort } from "../ports/mailer.ts";

/** No outbound mail vendor is configured. The port stays here so Better Auth never grows its own sender. */
export function configuredMailer(): MailerPort {
  return {
    send() {
      return Promise.reject(new AppError("unconfigured", "Mail is not configured."));
    },
  };
}
