import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { analyzeCrop, httpError, parseAnalysis } from "../src/api";
import { constrainPopup, resizePopup, popupPosition, sameViewport, screenshotRect, selectionRect, validSelection } from "../src/geometry";

const viewport = {width: 800, height: 600};
test("manual popup movement preserves size and clamps all edges", () => {
  const rect = {x: 100, y: 80, width: 420, height: 300};
  assert.deepEqual(constrainPopup(rect, viewport), rect);
  assert.deepEqual(constrainPopup({...rect, x: -900, y: 900}, viewport), {...rect, x: 8, y: 292});
  assert.deepEqual(constrainPopup({...rect, x: 900, y: -900}, viewport), {...rect, x: 372, y: 8});
});

test("manual popup fits smaller viewports while retaining accessible dimensions", () => {
  assert.deepEqual(constrainPopup({x: 700, y: 500, width: 1000, height: 800}, {width: 280, height: 180}),
    {x: 8, y: 8, width: 264, height: 164});
  assert.deepEqual(constrainPopup({x: 8, y: 8, width: 1, height: 1}, viewport),
    {x: 8, y: 8, width: 320, height: 220});
});

test("right, bottom and corner resizing preserve the opposite edge and respect limits", () => {
  const rect = {x: 100, y: 80, width: 420, height: 300};
  assert.deepEqual(resizePopup(rect, {x: 100, y: 100}, "right", viewport), {...rect, width: 520});
  assert.deepEqual(resizePopup(rect, {x: 100, y: 100}, "bottom", viewport), {...rect, height: 400});
  assert.deepEqual(resizePopup(rect, {x: 900, y: 900}, "corner", viewport), {...rect, width: 692, height: 512});
  assert.deepEqual(resizePopup(rect, {x: -900, y: -900}, "corner", viewport), {...rect, width: 320, height: 220});
  assert.deepEqual(resizePopup(rect, {x: 0, y: 0}, "corner", viewport), rect);
});
const response = () => ({original_text: "猫", translation: "Cat", processing: {ocr_ms: 1, translation_ms: 2, analysis_ms: 3, total_ms: 8}, tokens: [{
  surface: "猫", reading: "ねこ", lemma: "猫", dictionary_form: "猫", part_of_speech: "noun", conjugation_type: null, conjugation_form: null,
  meanings: [{entry_id: 1, glosses: ["cat"], parts_of_speech: ["noun"], spellings: [], readings: [], notes: [], labels: []}],
}]});

test("selection works in all drag directions and clamps outside viewport", () => {
  assert.deepEqual(selectionRect({x: 200, y: 300}, {x: 10, y: 20}, viewport), {x: 10, y: 20, width: 190, height: 280});
  assert.deepEqual(selectionRect({x: -10, y: -20}, {x: 900, y: 700}, viewport), {x: 0, y: 0, ...viewport});
  assert.equal(validSelection({x: 1, y: 1, width: 1, height: 2}, viewport), false);
  assert.equal(validSelection({x: NaN, y: 0, width: 10, height: 10}, viewport), false);
});

test("capture scales from actual screenshot dimensions for DPR and zoom", () => {
  const rect = {x: 10, y: 20, width: 100, height: 80};
  assert.deepEqual(screenshotRect(rect, viewport, {width: 1600, height: 1200}), {x: 20, y: 40, width: 200, height: 160});
  assert.deepEqual(screenshotRect(rect, viewport, {width: 1000, height: 750}), {x: 12, y: 25, width: 126, height: 100});
  assert.deepEqual(screenshotRect({x: 796, y: 596, width: 4, height: 4}, viewport, viewport), {x: 796, y: 596, width: 4, height: 4});
  assert.throws(() => screenshotRect({x: 800, y: 1, width: 10, height: 10}, viewport, viewport));
});

test("capture invalidated by scroll, resize, or pinch zoom", () => {
  const a = {...viewport, scrollX: 0, scrollY: 1200, scale: 1};
  assert.equal(sameViewport(a, {...a}), true);
  assert.equal(sameViewport(a, {...a, scrollY: 1201}), false);
  assert.equal(sameViewport(a, {...a, scale: 2}), false);
  assert.equal(sameViewport(a, {...a, width: 801}), false);
});

test("popup stays inside viewport at each edge", () => {
  for (const x of [0, 400, 799]) for (const y of [0, 300, 599]) {
    const point = popupPosition({x, y, width: 40, height: 30}, {width: 420, height: 400}, viewport);
    assert.ok(point.x >= 8 && point.y >= 8);
    assert.ok(point.x + 420 <= 792 && point.y + 400 <= 592);
  }
});

test("response validates nested types and nullable translation", () => {
  assert.deepEqual(parseAnalysis(response()), response());
  assert.equal(parseAnalysis({...response(), translation: null}).translation, null);
  assert.throws(() => parseAnalysis({original_text: "猫"}));
  assert.throws(() => parseAnalysis({...response(), processing: {ocr_ms: NaN}}));
  assert.throws(() => parseAnalysis({...response(), tokens: [{...response().tokens[0], reading: 12}]}));
  assert.throws(() => parseAnalysis({...response(), tokens: [{...response().tokens[0], meanings: [{entry_id: 1, glosses: [42]}]}]}));
  const text = '<img src=x onerror="alert(1)">';
  assert.equal(parseAnalysis({...response(), original_text: text}).original_text, text); // UI must render as textContent.
});

test("friendly HTTP messages never require raw server errors", () => {
  assert.match(httpError(503), /models or dictionary/);
  assert.match(httpError(429), /another crop/);
  assert.match(httpError(500), /Local analysis failed/);
});

test("request sends only crop to fixed localhost endpoint and parses JSON", async context => {
  context.mock.method(globalThis, "fetch", async (url: string, options: RequestInit) => {
    assert.equal(url, "http://127.0.0.1:8765/api/v1/analyze-image");
    assert.equal(options.method, "POST");
    assert.equal(options.credentials, "omit");
    assert.equal((options.headers as Record<string, string>)["X-YomiScan-Client"], "study-extension-v1");
    assert.equal(((options.body as FormData).get("file") as Blob).size, 4);
    return new Response(JSON.stringify(response()), {status: 200});
  });
  assert.equal((await analyzeCrop(new Blob(["crop"]), new AbortController().signal)).translation, "Cat");
});

test("offline, invalid JSON, invalid schema, and HTTP errors are handled", async context => {
  const mocked = context.mock.method(globalThis, "fetch", async () => { throw new TypeError("Failed to fetch"); });
  const call = () => analyzeCrop(new Blob(["crop"]), new AbortController().signal);
  await assert.rejects(call, /Start the local server/);
  mocked.mock.mockImplementation(async () => new Response("not json"));
  await assert.rejects(call, /invalid JSON/);
  mocked.mock.mockImplementation(async () => new Response("{}"));
  await assert.rejects(call, /Invalid analysis/);
  mocked.mock.mockImplementation(async () => new Response("sensitive traceback", {status: 500}));
  await assert.rejects(call, /Local analysis failed/);
});

test("aborted requests produce useful timeout guidance", async context => {
  const controller = new AbortController(); controller.abort();
  context.mock.method(globalThis, "fetch", async () => { throw new DOMException("Aborted", "AbortError"); });
  await assert.rejects(() => analyzeCrop(new Blob(), controller.signal), /cancelled or timed out/);
});

test("manifest limits access to active tab and loopback; no content scripts run automatically", async () => {
  const manifest = JSON.parse(await readFile("manifest.json", "utf8"));
  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(manifest.permissions, ["activeTab", "scripting"]);
  assert.deepEqual(manifest.host_permissions, ["http://127.0.0.1/*"]);
  assert.equal(manifest.content_scripts, undefined);
});
