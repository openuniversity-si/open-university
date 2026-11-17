import { handleAuthRequest } from "@/identity/server/handler.ts";

export const runtime = "nodejs";
export const GET = handleAuthRequest;
export const POST = handleAuthRequest;
