import { createReadStream, existsSync } from "node:fs";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const distDirectory = resolve(fileURLToPath(new URL("./dist/", import.meta.url)));
const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webmanifest": "application/manifest+json",
  ".woff2": "font/woff2",
};

createServer((request, response) => {
  let pathname;
  try {
    pathname = decodeURIComponent(new URL(request.url ?? "/", "http://localhost").pathname);
  } catch {
    response.writeHead(400).end("Bad request");
    return;
  }

  const requestedFile = resolve(distDirectory, `.${pathname}`);
  const isInsideDist = requestedFile === distDirectory.slice(0, -1)
    || requestedFile.startsWith(`${distDirectory}${sep}`);
  if (!isInsideDist) {
    response.writeHead(400).end("Bad request");
    return;
  }

  const filePath = existsSync(requestedFile)
    ? requestedFile
    : extname(pathname) ? null : resolve(distDirectory, "index.html");
  if (!filePath) {
    response.writeHead(404).end("Not found");
    return;
  }
  response.setHeader("Content-Type", mimeTypes[extname(filePath)] ?? "application/octet-stream");
  createReadStream(filePath)
    .on("error", () => response.writeHead(404).end("Not found"))
    .pipe(response);
}).listen(Number(process.env.PORT) || 5173, "0.0.0.0");
