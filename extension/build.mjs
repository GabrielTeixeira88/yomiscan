import { build, context } from "esbuild";
import { copyFile, mkdir } from "node:fs/promises";

if (process.argv.includes("--test")) {
  await build({entryPoints: ["tests/tests.ts"], outfile: ".test/tests.mjs", bundle: true,
    platform: "node", format: "esm", target: "node22"});
} else {
  await mkdir("dist", {recursive: true});
  await copyFile("manifest.json", "dist/manifest.json");
  await copyFile("offscreen.html", "dist/offscreen.html");
  await copyFile("image-access.html", "dist/image-access.html");
  const options = [
    {entryPoints: ["src/background.ts"], outfile: "dist/background.js", format: "esm"},
    {entryPoints: ["src/content.ts"], outfile: "dist/content.js", format: "iife"},
    {entryPoints: ["src/offscreen.ts"], outfile: "dist/offscreen.js", format: "esm"},
    {entryPoints: ["src/image-access.ts"], outfile: "dist/image-access.js", format: "esm"},
  ];
  for (const entry of options) {
    const settings = {...entry, bundle: true, target: "chrome120", sourcemap: true};
    if (process.argv.includes("--watch")) {
      await (await context(settings)).watch();
    } else {
      await build(settings);
    }
  }
  if (process.argv.includes("--watch")) console.log("Watching TypeScript; reload the extension after changes.");
}
