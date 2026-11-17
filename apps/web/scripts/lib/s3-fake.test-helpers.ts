import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

/** In-process S3 stand-in: path-style HEAD/GET/PUT(If-None-Match)/DELETE; rejects unsigned requests. */
export async function startFakeS3(accessKeyId: string): Promise<{ endpoint: string; objects: Map<string, Buffer>; requests: string[]; close(): Promise<void> }> {
  const objects = new Map<string, Buffer>();
  const requests: string[] = [];
  const server: Server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on("data", (chunk: Buffer) => chunks.push(chunk));
    request.on("end", () => {
      const key = decodeURIComponent(request.url ?? "");
      requests.push(`${request.method ?? ""} ${key}`);
      if (!String(request.headers.authorization).startsWith(`AWS4-HMAC-SHA256 Credential=${accessKeyId}/`)) { response.writeHead(403).end(); return; }
      const body = objects.get(key);
      if (request.method === "PUT" && request.headers["x-amz-copy-source"]) {
        if (request.headers["cf-copy-destination-if-none-match"] === "*" && body) { response.writeHead(412).end(); return; }
        const source = objects.get(decodeURIComponent(String(request.headers["x-amz-copy-source"])));
        if (!source) { response.writeHead(404).end(); return; }
        objects.set(key, Buffer.from(source));
        response.writeHead(200, { "Content-Type": "application/xml" }).end('<CopyObjectResult><ETag>"x"</ETag></CopyObjectResult>'); return;
      }
      if (request.method === "PUT") {
        if (request.headers["if-none-match"] === "*" && body) { response.writeHead(412).end(); return; }
        objects.set(key, Buffer.concat(chunks)); response.writeHead(200, { ETag: '"x"' }).end(); return;
      }
      if (request.method === "DELETE") { objects.delete(key); response.writeHead(204).end(); return; }
      if (!body) { response.writeHead(404).end(); return; }
      response.writeHead(200, { "Content-Length": String(body.length) }).end(request.method === "HEAD" ? undefined : body);
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return { endpoint: `http://127.0.0.1:${String(port)}`, objects, requests, close: () => new Promise((resolve) => { server.close(() => { resolve(); }); }) };
}
