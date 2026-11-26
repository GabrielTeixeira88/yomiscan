import { build, context } from "esbuild";
import { copyFile, mkdir, writeFile } from "node:fs/promises";
import { thirdPartyNotices } from "./tools/notices.mjs";

if (process.argv.includes("--test")) {
  await build({entryPoints: ["tests/tests.ts"], outfile: ".test/tests.mjs", bundle: true,
    platform: "node", format: "esm", target: "node22"});
  // Opt-in lexical parity harness; the WASM packages load their own files from node_modules.
  await build({entryPoints: ["tests/lexical-parity.ts"], outfile: ".test/lexical-parity.mjs", bundle: true,
    platform: "node", format: "esm", target: "node22", external: ["lindera-wasm-unidic", "@sqlite.org/sqlite-wasm"]});
  await build({entryPoints: ["tests/browser-support.ts"], outfile: ".test/browser-support.mjs", bundle: true,
    platform: "node", format: "esm", target: "node22"});
} else {
  await mkdir("dist", {recursive: true});
  await copyFile("manifest.json", "dist/manifest.json");
  await copyFile("offscreen.html", "dist/offscreen.html");
  await copyFile("image-access.html", "dist/image-access.html");
  await copyFile("library.html", "dist/library.html");
  for (const page of ["welcome.html", "about.html", "pages.css"]) await copyFile(page, `dist/${page}`);
  await mkdir("dist/icons", {recursive: true});
  for (const size of [16, 32, 48, 128]) await copyFile(`icons/icon-${size}.png`, `dist/icons/icon-${size}.png`);
  // Licenses travel with the code: YomiScan's own, and every shipped package's (tools/notices.mjs).
  await copyFile("../LICENSE", "dist/LICENSE.txt");
  await writeFile("dist/THIRD-PARTY-NOTICES.txt", thirdPartyNotices());
  // Browser engine (Stage 5a): ONNX Runtime Web, loaded at runtime by the offscreen document.
  // ort.wasm uses the plain threaded build; ort.webgpu uses the asyncify build.
  await mkdir("dist/ort", {recursive: true});
  for (const name of ["ort.wasm.min.mjs", "ort.webgpu.min.mjs", "ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm",
    "ort-wasm-simd-threaded.asyncify.mjs", "ort-wasm-simd-threaded.asyncify.wasm"])
    await copyFile(`node_modules/onnxruntime-web/dist/${name}`, `dist/ort/${name}`);
  // lindera (Japanese tokenizer, UniDic inside): its WASM ships with the extension, because the
  // Chrome Web Store allows no remotely loaded code, WASM included (Stage 6 increment 4).
  await mkdir("dist/lindera", {recursive: true});
  await copyFile("node_modules/lindera-wasm-unidic/lindera_wasm_unidic_bg.wasm", "dist/lindera/lindera_wasm_unidic_bg.wasm");
  // sqlite-wasm (JMdict lookups); its engine is small and ships with the extension.
  await mkdir("dist/sqlite", {recursive: true});
  await copyFile("node_modules/@sqlite.org/sqlite-wasm/dist/sqlite3.wasm", "dist/sqlite/sqlite3.wasm");
  const options = [
    {entryPoints: ["src/background.ts"], outfile: "dist/background.js", format: "esm"},
    {entryPoints: ["src/content.ts"], outfile: "dist/content.js", format: "iife"},
    {entryPoints: ["src/offscreen.ts"], outfile: "dist/offscreen.js", format: "esm"},
    {entryPoints: ["src/image-access.ts"], outfile: "dist/image-access.js", format: "esm"},
    {entryPoints: ["src/library-page.ts"], outfile: "dist/library.js", format: "esm"},
    {entryPoints: ["src/welcome-page.ts"], outfile: "dist/welcome.js", format: "esm"},
    {entryPoints: ["src/about-page.ts"], outfile: "dist/about.js", format: "esm"},
  ];
  for (const entry of options) {
    const settings = {...entry, bundle: true, target: "chrome120", sourcemap: !process.argv.includes('--release')};
    if (process.argv.includes("--watch")) {
      await (await context(settings)).watch();
    } else {
      await build(settings);
    }
  }
  if (process.argv.includes("--watch")) console.log("Watching TypeScript; reload the extension after changes.");
}
