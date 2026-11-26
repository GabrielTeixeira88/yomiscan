// Draws the extension icon (icons/icon-<size>.png) from simple shapes, with no image tools or
// fonts: a speech bubble holding three vertical text lines, the first with a furigana mark.
// Deterministic; rerun after changing the shapes: node tools/icons.mjs (from extension/).
import {mkdir, writeFile} from "node:fs/promises";
import {crc32, deflateSync} from "node:zlib";

const GREEN = [35, 93, 60], WHITE = [255, 253, 248], GOLD = [242, 193, 78];

/** Shapes in a 128 x 128 design space, bottom to top. */
const roundedRect = (x0, y0, x1, y1, r) => (x, y) => {
  const dx = Math.max(x0 + r - x, 0, x - (x1 - r)), dy = Math.max(y0 + r - y, 0, y - (y1 - r));
  return x >= x0 && x <= x1 && y >= y0 && y <= y1 && dx * dx + dy * dy <= r * r;
};
const triangle = ([ax, ay], [bx, by], [cx, cy]) => (x, y) => {
  const s = (px, py, qx, qy) => (x - qx) * (py - qy) - (px - qx) * (y - qy);
  const d1 = s(ax, ay, bx, by), d2 = s(bx, by, cx, cy), d3 = s(cx, cy, ax, ay);
  return !((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0));
};
/** A vertical bar with round ends (a line of vertical text). */
const bar = (cx, y0, y1, width) => (x, y) => {
  const r = width / 2, cy = Math.min(Math.max(y, y0 + r), y1 - r);
  return (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
};
const layers = [
  [GREEN, roundedRect(0, 0, 128, 128, 28)],
  [WHITE, roundedRect(16, 18, 112, 92, 30)],
  [WHITE, triangle([34, 80], [60, 88], [26, 112])],
  [GREEN, bar(84, 32, 80, 11)],
  [GREEN, bar(64, 32, 72, 11)],
  [GREEN, bar(44, 32, 62, 11)],
  [GOLD, bar(96, 34, 50, 5)],
];

/** `pad` pixels of transparent margin on each side (the store wants 96 px of art in the 128 px icon). */
function png(size, pad = 0) {
  const samples = 4, rows = [];
  for (let py = 0; py < size; py++) {
    const row = [0];  // PNG filter type 0 per row
    for (let px = 0; px < size; px++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let sy = 0; sy < samples; sy++) for (let sx = 0; sx < samples; sx++) {
        const art = size - 2 * pad;
        const x = (px - pad + (sx + .5) / samples) * 128 / art, y = (py - pad + (sy + .5) / samples) * 128 / art;
        let color = null;
        for (const [fill, inside] of layers) if (inside(x, y)) color = fill;
        if (color) {r += color[0]; g += color[1]; b += color[2]; a++;}
      }
      // Average over covered samples (no dark fringe), alpha from coverage.
      row.push(...(a ? [r / a, g / a, b / a].map(Math.round) : [0, 0, 0]), Math.round(255 * a / samples ** 2));
    }
    rows.push(...row);
  }
  const chunk = (type, data) => {
    const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const out = Buffer.alloc(8 + data.length + 4);
    out.writeUInt32BE(data.length, 0); body.copy(out, 4); out.writeUInt32BE(crc32(body), 8 + data.length);
    return out;
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0); header.writeUInt32BE(size, 4); header.set([8, 6, 0, 0, 0], 8);  // 8-bit RGBA
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.from(rows), {level: 9})), chunk("IEND", Buffer.alloc(0))]);
}

await mkdir("icons", {recursive: true});
for (const size of [16, 32, 48]) await writeFile(`icons/icon-${size}.png`, png(size));
await writeFile("icons/icon-128.png", png(128, 16));
console.log("Wrote icons/icon-{16,32,48,128}.png");
