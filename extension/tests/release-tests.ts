import test from "node:test";
import assert from "node:assert/strict";
import {resolveEngine, type EngineChoice} from "../src/engine-mode";
import {storageShortfall, STORAGE_MARGIN, type EngineStatus} from "../src/engine/engine";
import {ArtifactStore, type ArtifactComponent} from "../src/engine/artifacts";
import {progressLine, setupLines, sourceLabel, type EngineState} from "../src/chapter/engine-setup";
import host from "../src/engine/artifact-host.json";

test("Automatic uses installed browser models, then a running backend, then asks for setup", async () => {
  const resolve = async (choice: EngineChoice, ready: boolean, running: boolean) => {
    const calls: string[] = [];
    const mode = await resolveEngine(choice, async () => {calls.push('browser');return ready;}, async () => {calls.push('backend');return running;});
    return {mode, calls};
  };
  assert.deepEqual(await resolve('auto', true, true), {mode: 'browser', calls: ['browser']}, "installed models win without probing the backend");
  assert.deepEqual(await resolve('auto', false, true), {mode: 'local', calls: ['browser', 'backend']});
  assert.deepEqual(await resolve('auto', false, false), {mode: 'setup', calls: ['browser', 'backend']});
  assert.deepEqual(await resolve('local', true, false), {mode: 'local', calls: []}, "an explicit local choice is never second-guessed");
  assert.deepEqual(await resolve('browser', false, true), {mode: 'setup', calls: ['browser']}, "explicit browser without models needs setup");
});

test("a download that cannot fit is refused before it starts, with the space to free", () => {
  const need = 550e6;
  assert.equal(storageShortfall(need, {usage: 0, quota: 50e9}), null);
  assert.equal(storageShortfall(0, {usage: 0, quota: 0}), null, "nothing missing needs no space");
  assert.equal(storageShortfall(need, null), null, "unknown storage does not block");
  const message = storageShortfall(need, {usage: 100e6, quota: 600e6})!;
  assert.match(message, /need 550 MB and Chrome reports 500 MB available/);
  assert.match(message, new RegExp(`Free at least ${Math.ceil((need + STORAGE_MARGIN - 500e6) / 1e6)} MB`));
});

test("running out of storage while saving names the file, keeps finished files and the cause", async () => {
  const quota = new DOMException("full", "QuotaExceededError"), stored = new Map<string, Response>();
  const storage = async () => ({match: async (k: string) => stored.get(k), delete: async (k: string) => stored.delete(k),
    put: async (k: string, r: Response) => {if (stored.size) throw quota;stored.set(k, r);}});
  const component: ArtifactComponent = {id: 'c', kind: 'ocr', variant: 'int8', license: 'l', source: 's', files: [
    {path: 'c/one', bytes: 1, sha256: 'ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb'}, {path: 'c/two', bytes: 1, sha256: '3e23e8160039594a33894f6564e1b1348bbd7a0088d42c4acb73eeaed59c009d'}]};
  const store = new ArtifactStore(storage, async input => new Response(String(input).endsWith('one') ? 'a' : 'b'));
  const failed = await store.install(component, 'http://h/').then(() => null, (e: Error) => e);
  assert.ok(failed);
  assert.equal(failed.message, 'Chrome ran out of storage while saving c/two. Free some disk space, then download again; finished files are kept.');
  assert.equal(failed.cause, quota);
  assert.equal(stored.size, 1, "the finished first file stays stored for the next attempt");
});

const status = (over: Partial<EngineStatus> = {}): EngineStatus => ({backend: 'webgpu', isolated: true, threads: 8, bundle: 'b', loaded: false,
  install: {state: 'idle'}, missingBytes: 547e6, storage: null, persisted: false, required: [
    {id: 'detector', kind: 'detector', variant: 'fp16', bytes: 86e6, license: 'Apache-2.0', source: 's', installed: false},
    {id: 'translation-opus-ja-en', kind: 'translation', variant: 'fp16', bytes: 461e6, license: 'Apache-2.0', source: 's', installed: false}], ...over});

test("first-run setup states the size for this device, the host and how to remove the models", () => {
  const state: EngineState = {choice: 'auto', mode: 'setup', status: status(), evicted: false,
    source: 'https://huggingface.co/owner/yomiscan-browser-models/resolve/0123456789abcdef0123456789abcdef01234567/'};
  const lines = setupLines(state);
  assert.equal(lines.title, 'Download the reading models');
  assert.equal(lines.size, '547 MB for this computer (runs on your GPU)');
  assert.match(lines.source, /^From huggingface\.co\/owner\/yomiscan-browser-models\. /);
  assert.match(lines.source, /Nothing you read is uploaded\. Remove the models any time under Advanced → Browser engine\./);
  const evicted = setupLines({...state, evicted: true, status: status({backend: 'wasm'})});
  assert.equal(evicted.title, 'Download the reading models again');
  assert.match(evicted.body, /no longer stored\. Chrome can remove extension data when the disk is nearly full/);
  assert.match(evicted.size, /runs on your CPU/);
  assert.equal(sourceLabel('http://127.0.0.1:47620/'), '127.0.0.1:47620');
});

test("download progress counts finished components plus the current one", () => {
  const running = status({install: {state: 'running', progress: {component: 'translation-opus-ja-en', file: 'x', loaded: 100e6, total: 461e6}},
    required: status().required.map(c => c.id === 'detector' ? {...c, installed: true} : c)});
  assert.equal(progressLine(running), 'Downloading the translator: 186 of 547 MB');
  assert.equal(progressLine(status({install: {state: 'failed', error: 'HTTP 404'}})), 'Download stopped: HTTP 404');
  assert.equal(progressLine(status()), '');
});

test("the default model host is a plain folder URL, pinned to a commit when published", () => {
  const url = new URL(host.base);
  assert.ok(['http:', 'https:'].includes(url.protocol) && url.pathname.endsWith('/') && !url.search && !url.hash);
  if (host.repository !== null)
    assert.equal(host.base, `https://huggingface.co/${host.repository}/resolve/${host.revision}/`, "published sources must name an immutable commit");
});
