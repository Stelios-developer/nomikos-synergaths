import "dotenv/config";

import { createServer } from "node:http";
import { toNodeHandler } from "better-auth/node";

import { auth, pool } from "./auth.js";
import { isProduction } from "./runtime.js";

const port = Number(process.env.AUTH_PORT ?? 3001);
const host = process.env.AUTH_HOST ?? (isProduction ? "0.0.0.0" : "127.0.0.1");
const appOrigin = process.env.APP_ORIGIN ?? "http://localhost:5173";
const authHandler = toNodeHandler(auth);

const server = createServer(async (request, response) => {
  const origin = request.headers.origin;
  if (origin === appOrigin) {
    response.setHeader("Access-Control-Allow-Origin", origin);
    response.setHeader("Access-Control-Allow-Credentials", "true");
    response.setHeader("Vary", "Origin");
  }

  if (request.method === "OPTIONS") {
    response.writeHead(204, {
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    });
    response.end();
    return;
  }

  if (request.url?.startsWith("/api/auth")) {
    try {
      await authHandler(request, response);
    } catch {
      if (!response.headersSent) {
        response.writeHead(500, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ detail: "Authentication service error." }));
      }
    }
    return;
  }

  if (request.method === "GET" && request.url === "/health") {
    response.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
    response.end(JSON.stringify({ status: "ok" }));
    return;
  }

  response.writeHead(404, { "Content-Type": "application/json" });
  response.end(JSON.stringify({ detail: "Not found" }));
});

server.listen(port, host, () => {
  console.info(`Documents Made Clear auth service listening on port ${port}`);
});

async function shutdown() {
  server.close();
  await pool.end();
}

process.on("SIGTERM", () => void shutdown());
process.on("SIGINT", () => void shutdown());
