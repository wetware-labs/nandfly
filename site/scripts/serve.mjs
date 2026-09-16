// Zero-dep static file server for local dev/testing of site/. Not used in
// production (GitHub Pages serves the static files directly) -- this exists
// purely so `node site/scripts/serve.mjs` gives a local http://localhost
// origin for Playwright E2E and manual browser testing (fetch()/ES modules
// need a real origin, not file://).
//
// Run from the repo root: node site/scripts/serve.mjs [port]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const PORT = Number(process.argv[2]) || 8934;

const TYPES = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

const server = http.createServer((req, res) => {
  let reqPath = decodeURIComponent(req.url.split("?")[0]);
  if (reqPath === "/") reqPath = "/index.html";
  const full = path.join(ROOT, reqPath);
  if (!full.startsWith(ROOT)) {
    res.writeHead(403);
    res.end();
    return;
  }
  fs.readFile(full, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end(`not found: ${reqPath}`);
      return;
    }
    res.writeHead(200, { "content-type": TYPES[path.extname(full)] || "application/octet-stream" });
    res.end(data);
  });
});

server.listen(PORT, () => console.log(`serving site/ on http://localhost:${PORT}`));
