// The Chrome Web Store package: a clean release build of dist/, the store checks
// (tools/store-checks.mjs: no remote code, manifest, icons, licenses, size), then a reproducible
// ZIP (sorted entries, fixed dates) and a JSON report. Exit status 1 if any check fails.
//   node package.mjs [--out <folder>]     (default ../.cache/store-package)
import {execFileSync} from "node:child_process";
import {mkdir, readFile, rm, writeFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import path from "node:path";
import {crc32, deflateRawSync} from "node:zlib";
import {checkPackage, files} from "./tools/store-checks.mjs";

const args = process.argv.slice(2), at = args.indexOf("--out");
const out = path.resolve(at >= 0 ? args[at + 1] : "../.cache/store-package");

await rm("dist", {recursive: true, force: true});
execFileSync(process.execPath, ["build.mjs", "--release"], {stdio: "inherit"});
const problems = checkPackage("dist");
if (problems.length) {
  console.error("The package fails the store checks:\n- " + problems.join("\n- "));
  process.exit(1);
}

/** A ZIP with deflated entries in name order and the DOS date 1980-01-01, so equal inputs give equal bytes. */
function zip(entries) {
  const local = [], central = [];
  let offset = 0;
  for (const {name, data} of entries) {
    const nameBytes = Buffer.from(name, "utf8"), packed = deflateRawSync(data, {level: 9}), crc = crc32(data);
    const header = Buffer.alloc(30);
    header.writeUInt32LE(0x04034b50, 0); header.writeUInt16LE(20, 4); header.writeUInt16LE(0x0800, 6);  // UTF-8 names
    header.writeUInt16LE(8, 8); header.writeUInt16LE(0, 10); header.writeUInt16LE(0x21, 12);           // deflate, 1980-01-01
    header.writeUInt32LE(crc, 14); header.writeUInt32LE(packed.length, 18); header.writeUInt32LE(data.length, 22);
    header.writeUInt16LE(nameBytes.length, 26);
    const record = Buffer.alloc(46);
    record.writeUInt32LE(0x02014b50, 0); record.writeUInt16LE(0x0314, 4); record.writeUInt16LE(20, 6);
    record.writeUInt16LE(0x0800, 8); record.writeUInt16LE(8, 10); record.writeUInt16LE(0, 12); record.writeUInt16LE(0x21, 14);
    record.writeUInt32LE(crc, 16); record.writeUInt32LE(packed.length, 20); record.writeUInt32LE(data.length, 24);
    record.writeUInt16LE(nameBytes.length, 28); record.writeUInt32LE((0o100644 << 16) >>> 0, 38); record.writeUInt32LE(offset, 42);
    local.push(header, nameBytes, packed); central.push(record, nameBytes);
    offset += header.length + nameBytes.length + packed.length;
  }
  const directory = Buffer.concat(central), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(directory.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, directory, end]);
}

const names = files("dist");
const entries = await Promise.all(names.map(async name => ({name, data: await readFile(path.join("dist", name))})));
const manifest = JSON.parse(entries.find(e => e.name === "manifest.json").data.toString("utf8"));
const archive = zip(entries);
await mkdir(out, {recursive: true});
const file = path.join(out, `yomiscan-extension-${manifest.version}.zip`);
await writeFile(file, archive);
const report = {version: manifest.version, zip: path.basename(file), zip_bytes: archive.length,
  sha256: createHash("sha256").update(archive).digest("hex"),
  unpacked_bytes: entries.reduce((total, e) => total + e.data.length, 0), files: entries.length,
  largest: [...entries].sort((a, b) => b.data.length - a.data.length).slice(0, 5).map(e => ({name: e.name, bytes: e.data.length})),
  checks: ["manifest (MV3, name, description, version, permissions as listed)", "icons 16/32/48/128",
    "no remotely hosted code (scripts, imports, importScripts, remote .js/.wasm)", "pages load only packaged files",
    "no source maps or other file types", "LICENSE.txt and THIRD-PARTY-NOTICES.txt", "size budget"]};
await writeFile(path.join(out, "store-package-report.json"), JSON.stringify(report, null, 1) + "\n");
console.log(JSON.stringify(report, null, 1));
