// Chrome Web Store checks on a built extension folder (dist/), used by package.mjs. Each failed
// check is one line; an empty list means the folder may be packaged.
import {readFileSync, readdirSync, statSync} from "node:fs";
import path from "node:path";

/** The permissions the store listing justifies (docs/store/listing.md). Adding one is a listing change. */
export const PERMISSIONS = ["activeTab", "scripting", "offscreen", "storage", "unlimitedStorage", "nativeMessaging"];
export const HOST_PERMISSIONS = ["http://127.0.0.1/*"];
export const OPTIONAL_HOST_PERMISSIONS = ["http://*/*", "https://*/*"];
export const ICON_SIZES = [16, 32, 48, 128];
/** File types a package may hold; source maps, TypeScript and tests may not. */
const ALLOWED = /\.(?:js|mjs|wasm|html|css|json|png|txt)$/;
/** Our own budget, to notice accidental growth (the store accepts far larger packages). */
export const SIZE_BUDGET = 150 * 1024 * 1024;

export function files(root, dir = root) {
  return readdirSync(dir, {withFileTypes: true}).flatMap(entry => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? files(root, full) : [path.relative(root, full).split(path.sep).join("/")];
  }).sort();
}

function pngSize(bytes) {
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (!signature.every((b, i) => bytes[i] === b) || bytes.toString("ascii", 12, 16) !== "IHDR") return null;
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

/** Remote code: script or module URLs, importScripts, and code-like files on a remote host. */
export function remoteCode(name, text) {
  const found = [];
  const patterns = [
    [/importScripts\s*\(/g, "importScripts()"],
    [/\bimport\s*\(\s*["'`]https?:/g, "import() of a remote URL"],
    [/\bfrom\s*["']https?:/g, "static import from a remote URL"],
    [/<script\b[^>]*\bsrc\s*=\s*["']?(?:https?:)?\/\//gi, "<script> from a remote URL"],
    [/["'`]https?:\/\/[^"'`\s]+\.(?:m?js|wasm)(?:\?[^"'`\s]*)?["'`]/g, "a remote .js/.wasm URL"],
  ];
  for (const [pattern, label] of patterns) if (pattern.test(text)) found.push(`${name}: ${label}`);
  return found;
}

export function checkPackage(dir) {
  const problems = [], all = files(dir);
  const read = name => readFileSync(path.join(dir, name));
  let manifest;
  try {manifest = JSON.parse(read("manifest.json").toString("utf8"));} catch (error) {return [`manifest.json: ${error.message}`];}
  const same = (a = [], b) => a.length === b.length && a.every((x, i) => x === b[i]);
  if (manifest.manifest_version !== 3) problems.push("manifest_version must be 3");
  if (!manifest.name || manifest.name.length > 75) problems.push("name must be 1–75 characters");
  if (!manifest.description || manifest.description.length > 132) problems.push("description must be 1–132 characters");
  if (!/^\d+(?:\.\d+){0,3}$/.test(manifest.version ?? "")) problems.push("version must be 1–4 dot-separated integers");
  if (!same(manifest.permissions, PERMISSIONS)) problems.push(`permissions changed (${manifest.permissions}); update PERMISSIONS and the store listing's justifications`);
  if (!same(manifest.host_permissions, HOST_PERMISSIONS)) problems.push(`host_permissions changed (${manifest.host_permissions})`);
  if (!same(manifest.optional_host_permissions, OPTIONAL_HOST_PERMISSIONS)) problems.push(`optional_host_permissions changed (${manifest.optional_host_permissions})`);
  for (const key of ["content_scripts", "externally_connectable", "web_accessible_resources", "update_url"])
    if (manifest[key]) problems.push(`manifest declares ${key}, which the listing does not cover`);
  const scriptSrc = /script-src([^;]*)/.exec(manifest.content_security_policy?.extension_pages ?? "")?.[1].trim().split(/\s+/) ?? [];
  if (!same(scriptSrc, ["'self'", "'wasm-unsafe-eval'"])) problems.push(`extension pages may run only packaged scripts (script-src is "${scriptSrc.join(" ")}")`);
  // Every icon size for the store and Chrome's pages; the toolbar button needs the small ones.
  const icons = [...ICON_SIZES.map(size => ["icons", size, manifest.icons?.[size]]),
    ...ICON_SIZES.filter(size => size < 128).map(size => ["action.default_icon", size, manifest.action?.default_icon?.[size]])];
  for (const [owner, size, name] of icons) {
    if (!name) {problems.push(`${owner} lacks a ${size} px icon`); continue;}
    if (!all.includes(name)) {problems.push(`${owner} ${size}: ${name} is missing`); continue;}
    const dimensions = pngSize(read(name));
    if (!dimensions || dimensions[0] !== size || dimensions[1] !== size) problems.push(`${name} must be a ${size} x ${size} PNG`);
  }
  if (!all.includes(manifest.background?.service_worker)) problems.push("the background service worker is missing");
  for (const name of all) {
    if (!ALLOWED.test(name)) problems.push(`${name}: file type not allowed in the package`);
    if (!/\.(?:js|mjs|html)$/.test(name)) continue;
    const text = read(name).toString("utf8");
    problems.push(...remoteCode(name, text));
    if (name.endsWith(".html")) for (const [, ref] of text.matchAll(/<(?:script|link)\b[^>]*\b(?:src|href)\s*=\s*"([^"]+)"/g)) {
      if (/^[a-z]+:/i.test(ref) || ref.startsWith("//")) problems.push(`${name}: loads ${ref}; pages may load only packaged files`);
      else if (!all.includes(path.posix.join(path.posix.dirname(name), ref))) problems.push(`${name}: ${ref} is missing`);
    }
  }
  for (const name of ["LICENSE.txt", "THIRD-PARTY-NOTICES.txt"]) if (!all.includes(name)) problems.push(`${name} is missing`);
  const bytes = all.reduce((total, name) => total + statSync(path.join(dir, name)).size, 0);
  if (bytes > SIZE_BUDGET) problems.push(`the package holds ${(bytes / 2 ** 20).toFixed(0)} MiB, over the ${SIZE_BUDGET / 2 ** 20} MiB budget`);
  return problems;
}
