import { once } from "node:events";
import { Agent } from "node:http";
import { Worker } from "node:worker_threads";
import { request } from "@playwright/test";
import { expect, it, vi, type MockInstance } from "vitest";
import { applyLocalHttpPolicy, localHttpHeaders } from "./local-http.ts";

// Separate event loop: the server must be able to expire an idle socket while the client is paused.
const SERVER = `
  const { parentPort, workerData } = require("node:worker_threads");
  const { createServer } = require("node:http");
  let peer, connections = 0, received = 0;
  const server = createServer((req, res) => {
    received++;
    peer ??= req.socket;
    req.resume();
    res.end(JSON.stringify({ connections, received }));
  });
  server.on("connection", () => connections++);
  server.listen(0, "127.0.0.1", () => parentPort.postMessage(server.address().port));
  parentPort.on("message", (command) => {
    if (command === "stats") { parentPort.postMessage({ connections, received }); return; }
    const notify = () => {
      const signal = new Int32Array(workerData);
      Atomics.store(signal, 0, 1);
      Atomics.notify(signal, 0);
    };
    if (peer.destroyed) notify();
    else { peer.once("close", notify); peer.destroy(); }
  });
`;

async function withExpiredSocket(closeConnections: boolean) {
  const signal = new Int32Array(new SharedArrayBuffer(4));
  const server = new Worker(SERVER, { eval: true, workerData: signal.buffer });
  let api: Awaited<ReturnType<typeof request.newContext>> | undefined;
  let reuse: MockInstance<typeof Agent.prototype.reuseSocket> | undefined;
  let restoreTransport: (() => void) | undefined;
  try {
    const [port] = await once(server, "message") as [number];
    const baseURL = `http://127.0.0.1:${String(port)}`;
    api = await request.newContext({ baseURL });
    if (closeConnections) restoreTransport = applyLocalHttpPolicy(api, baseURL);
    expect((await api.get("/warmup")).status()).toBe(200);
    // eslint-disable-next-line @typescript-eslint/unbound-method -- The spy preserves the live agent receiver with .call(this) below.
    const original = Agent.prototype.reuseSocket;
    reuse = vi.spyOn(Agent.prototype, "reuseSocket").mockImplementation(function (this: Agent, socket, req) {
      original.call(this, socket, req);
      // Select the free socket first, then expire its peer before the client can write or process FIN.
      // The barrier replaces a long scheduler pause + the server's real idle timeout; no timing race/retry.
      server.postMessage("expire");
      expect(Atomics.wait(signal, 0, 0, 2_000)).not.toBe("timed-out");
    });
    if (closeConnections) {
      const response = await api.post("/probe", { data: {} });
      expect(response.status()).toBe(200);
      expect(await response.json()).toEqual({ connections: 2, received: 2 });
      expect(reuse).not.toHaveBeenCalled();
    } else {
      await expect(api.post("/probe", { data: {} })).rejects.toMatchObject({ code: "ECONNRESET" });
      expect(reuse).toHaveBeenCalledOnce();
      const stats = once(server, "message");
      server.postMessage("stats");
      expect((await stats)[0]).toEqual({ connections: 1, received: 1 });
    }
  } finally {
    reuse?.mockRestore();
    restoreTransport?.();
    await api?.dispose();
    await server.terminate();
  }
}

it("reproduces APIRequestContext's idle socket reset before any POST reaches the server", async () => {
  await withExpiredSocket(false);
});

it("the local harness avoids the reset with a fresh connection and no retry", async () => {
  await withExpiredSocket(true);
});

it("uses the policy for every local HTTP loopback form", () => {
  for (const host of ["127.0.0.1", "localhost", "[::1]"]) {
    expect(localHttpHeaders(`http://${host}:3100`)).toEqual({ Connection: "close" });
  }
});

it("leaves remote and HTTPS transports alone", () => {
  for (const baseURL of [undefined, "https://openuniversity.si", "http://example.invalid", "https://127.0.0.1:3100"]) {
    expect(localHttpHeaders(baseURL)).toEqual({});
  }
});
