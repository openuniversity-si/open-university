export interface MailerMessage {
  readonly to: string;
  readonly subject: string;
  readonly html: string;
}

export interface MailerPort {
  send(message: MailerMessage): Promise<void>;
}
