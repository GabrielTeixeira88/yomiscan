import test from "node:test";
import assert from "node:assert/strict";
import {cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import path from "node:path";
import {PERMISSIONS, checkPackage, remoteCode} from "../tools/store-checks.mjs";
import {shippedPackages} from "../tools/notices.mjs";

const manifest = JSON.parse(readFileSync("manifest.json", "utf8"));

/** A minimal package folder that passes, built from the real manifest and icons. */
function fixture(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "yomiscan-store-"));
  writeFileSync(path.join(dir, "manifest.json"), JSON.stringify(manifest));
  cpSync("icons", path.join(dir, "icons"), {recursive: true});
  for (const name of ["background.js", "LICENSE.txt", "THIRD-PARTY-NOTICES.txt"]) writeFileSync(path.join(dir, name), "");
  writeFileSync(path.join(dir, "page.html"), '<link rel="stylesheet" href="page.css"><script src="page.js"></script>');
  for (const name of ["page.css", "page.js"]) writeFileSync(path.join(dir, name), "");
  return dir;
}

test("the store checks pass a clean package and name each problem", () => {
  const dir = fixture();
  try {
    assert.deepEqual(checkPackage(dir), []);
    writeFileSync(path.join(dir, "page.js.map"), "{}");
    writeFileSync(path.join(dir, "late.js"), 'const m = await import("https://cdn.example/x.mjs");');
    writeFileSync(path.join(dir, "page.html"), '<script src="https://cdn.example/a.js"></script><script src="gone.js"></script>');
    writeFileSync(path.join(dir, "manifest.json"), JSON.stringify({...manifest, permissions: [...PERMISSIONS, "tabs"],
      content_security_policy: {extension_pages: "script-src 'self' https://cdn.example; object-src 'none'"}, icons: {...manifest.icons, 128: "icons/icon-48.png"}}));
    const problems = checkPackage(dir).join("\n");
    for (const expected of [/page\.js\.map: file type not allowed/, /late\.js: import\(\) of a remote URL/, /page\.html: <script> from a remote URL/,
      /page\.html: loads https:\/\/cdn\.example\/a\.js/, /page\.html: gone\.js is missing/, /permissions changed/, /script-src/, /icon-48\.png must be a 128 x 128 PNG/])
      assert.match(problems, expected);
  } finally {rmSync(dir, {recursive: true, force: true});}
});

test("remote-code patterns: model and page URLs are data, script URLs are code", () => {
  assert.deepEqual(remoteCode("a.js", 'fetch("https://huggingface.co/x/resolve/r/model.onnx"); fetch(base + "/page.png")'), []);
  assert.equal(remoteCode("a.js", "importScripts('x.js')").length, 1);
  assert.equal(remoteCode("a.js", 'const u = "https://cdn.example/lib.wasm";').length, 1);
  assert.match(remoteCode("a.js", 'import x from "https://cdn.example/lib.js";').join(), /static import from a remote URL/);
});

test("the store listing justifies every permission the manifest requests", () => {
  assert.deepEqual(manifest.permissions, PERMISSIONS);
  const listing = readFileSync("../docs/store/listing.md", "utf8");
  for (const permission of [...PERMISSIONS, ...manifest.host_permissions, ...manifest.optional_host_permissions])
    assert.ok(listing.includes("`" + permission + "`"), `${permission} is justified in docs/store/listing.md`);
});

test("third-party notices cover the shipped packages and leave out type-only ones", () => {
  const names = shippedPackages().map(p => p.name);
  for (const name of ["onnxruntime-web", "lindera-wasm-unidic", "@sqlite.org/sqlite-wasm", "@huggingface/tokenizers", "protobufjs"])
    assert.ok(names.includes(name), name);
  assert.ok(!names.some(name => name.startsWith("@types/") || name === "undici-types"));
});
