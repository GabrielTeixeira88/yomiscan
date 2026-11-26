// THIRD-PARTY-NOTICES.txt for the packaged extension: the license of every npm package that
// ships in it (the production dependency tree in package-lock.json, minus type-only packages),
// plus UniDic, whose dictionary is built into lindera's WASM. A package without its own license
// file needs a text in licenses/ (FALLBACKS); a missing license fails the build.
import {readFileSync, readdirSync, existsSync} from "node:fs";

const TYPES_ONLY = name => name.startsWith("@types/") || name === "undici-types";
const FALLBACKS = {"onnxruntime-web": "onnxruntime.txt", "onnxruntime-common": "onnxruntime.txt",
  "@sqlite.org/sqlite-wasm": "sqlite-wasm.txt", "guid-typescript": "guid-typescript.txt"};

/** The production dependency closure, by package name. */
export function shippedPackages(lock = JSON.parse(readFileSync("package-lock.json", "utf8"))) {
  const seen = new Map(), queue = Object.keys(lock.packages[""].dependencies ?? {});
  while (queue.length) {
    const name = queue.shift();
    if (seen.has(name) || TYPES_ONLY(name)) continue;
    const info = lock.packages[`node_modules/${name}`];
    if (!info) throw new Error(`package-lock.json has no entry for ${name}`);
    seen.set(name, info);
    queue.push(...Object.keys(info.dependencies ?? {}));
  }
  return [...seen].sort(([a], [b]) => a.localeCompare(b)).map(([name, info]) => ({name, version: info.version, license: info.license}));
}

function licenseText(name) {
  const dir = `node_modules/${name}`;
  const own = existsSync(dir) ? readdirSync(dir).find(file => /^(licen[cs]e|copying)/i.test(file)) : undefined;
  if (own) return readFileSync(`${dir}/${own}`, "utf8");
  if (FALLBACKS[name]) return readFileSync(`licenses/${FALLBACKS[name]}`, "utf8");
  throw new Error(`${name} ships without a license file; add one to licenses/ and FALLBACKS in tools/notices.mjs`);
}

export function thirdPartyNotices() {
  const sections = shippedPackages().map(p => [`${p.name} ${p.version} (${p.license})`, licenseText(p.name)]);
  sections.push(["UniDic 2.1.2 (BSD-3-Clause), the dictionary built into lindera-wasm-unidic", readFileSync("licenses/UniDic.txt", "utf8")]);
  const rule = "=".repeat(78);
  return ["YomiScan includes the following third-party software. YomiScan's own code is MIT-licensed (see LICENSE).",
    "Models and JMdict are downloaded on first use, not shipped here; the About & licenses page lists them.", "",
    ...sections.flatMap(([title, text]) => [rule, title, rule, "", text.trim(), ""])].join("\n");
}
