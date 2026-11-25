import test from "node:test";
import assert from "node:assert/strict";
import {NATIVE_HOST, companionConnection, companionStatus, parsePrepare, parseStart, type NativeMessaging, type SessionStore} from "../src/companion";
import {companionProgress, companionSetupLines} from "../src/chapter/companion-setup";
import {resolveEngine} from "../src/engine-mode";
import {localFetch} from "../src/local";

const TOKEN = "t".repeat(43);

function session(): SessionStore & {data: Record<string, unknown>} {
  const data: Record<string, unknown> = {};
  return {data, get: async key => key in data ? {[key]: data[key]} : {}, set: async items => {Object.assign(data, items);},
    remove: async key => {delete data[key];}};
}
function native(replies: ((message: {type: string}) => unknown)[]): NativeMessaging & {sent: {type: string}[]} {
  const sent: {type: string}[] = [];
  return {sent, sendNativeMessage: async (host, message) => {
    assert.equal(host, NATIVE_HOST);
    sent.push(message as {type: string});
    const reply = replies.shift()!(message as {type: string});
    if (reply instanceof Error) throw reply;
    return reply;
  }};
}

test("Automatic prefers a ready companion, then browser models, then a running backend", async () => {
  const calls: string[] = [];
  const probe = (name: string, value: boolean) => async () => {calls.push(name); return value;};
  assert.equal(await resolveEngine('auto', probe('browser', true), probe('backend', true), probe('companion', true)), 'local');
  assert.deepEqual(calls, ['companion']);
  calls.length = 0;
  assert.equal(await resolveEngine('auto', probe('browser', true), probe('backend', true), probe('companion', false)), 'browser');
  assert.deepEqual(calls, ['companion', 'browser']);
  calls.length = 0;
  assert.equal(await resolveEngine('browser', probe('browser', true), probe('backend', true), probe('companion', true)), 'browser');
  assert.deepEqual(calls, ['browser'], "an explicit browser choice never starts the companion");
});

test("companion status: not installed, ready, missing models, cached for 30 s", async () => {
  let now = 0;
  const store = session();
  const missing = native([() => new Error("Specified native messaging host not found."),
    () => ({ok: true, version: "0.1.0", models: {ready: false, missing: ["dictionary"]}}),
    () => ({ok: true, version: "0.1.0", models: {ready: true, missing: []}})]);
  const deps = {native: missing, session: store, now: () => now};
  assert.deepEqual(await companionStatus(deps), {installed: false, ready: false, missing: []});
  assert.deepEqual(await companionStatus(deps), {installed: false, ready: false, missing: []}, "cached");
  now = 31_000;
  assert.deepEqual(await companionStatus(deps), {installed: true, ready: false, missing: ["dictionary"], version: "0.1.0",
    bytes: undefined, source: undefined, prepare: null});
  assert.equal((await companionStatus(deps, true)).ready, true);
  assert.equal(missing.sent.length, 3);
  const broken = native([() => ({ok: false, error: "OSError: disk full"})]);
  assert.deepEqual(await companionStatus({native: broken, session: session(), now: () => 0}),
    {installed: true, ready: false, missing: [], error: "OSError: disk full"});
});

test("companion connection is started once, kept in session storage, and restarted on request", async () => {
  const store = session();
  const host = native([() => ({ok: true, port: 50001, token: TOKEN}), () => ({ok: true, port: 50002, token: TOKEN})]);
  const deps = {native: host, session: store, now: () => 0};
  const first = await companionConnection(false, deps);
  assert.deepEqual(first, {base: "http://127.0.0.1:50001", companion: true, started: true,
    headers: {"X-YomiScan-Client": "study-extension-v1", "X-YomiScan-Token": TOKEN}});
  const reused = await companionConnection(false, deps);
  assert.equal(reused.base, "http://127.0.0.1:50001");
  assert.equal(reused.started, false);
  assert.equal((await companionConnection(true, deps)).base, "http://127.0.0.1:50002");
  assert.deepEqual(host.sent.map(m => m.type), ["start", "start"]);
  assert.throws(() => parseStart({ok: true, port: 80, token: TOKEN}), /invalid address/);
  assert.throws(() => parseStart({ok: true, port: 50001, token: "short"}), /invalid address/);
  assert.throws(() => parseStart({ok: false, error: "TimeoutError: slow"}), /did not start: TimeoutError: slow/);
});

test("localFetch waits for a launched engine's models, sends the token, and relaunches one that went idle", async () => {
  const g = globalThis as unknown as {chrome?: unknown; fetch: typeof fetch};
  const saved = {chrome: g.chrome, fetch: g.fetch};
  const store = session(), local: Record<string, unknown> = {};
  let starts = 0;
  const requests: {url: string; token?: string}[] = [];
  let polls = 0;
  g.chrome = {runtime: {sendNativeMessage: async (_host: string, message: {type: string}) => message.type === "status" ?
      {ok: true, models: {ready: true, missing: []}} : {ok: true, port: 50000 + ++starts, token: TOKEN}},
    storage: {session: store, local: {get: async (key: string) => ({[key]: local[key]})}}};
  g.fetch = (async (url: string, init: RequestInit) => {
    if (url.endsWith("/api/v1/readiness") && init.signal) {  // the launch wait: initializing once, then ready
      polls++;
      return new Response(JSON.stringify({initialization: polls === 1 ? "initializing" : "ready"}), {status: 200});
    }
    requests.push({url, token: (init.headers as Record<string, string>)["X-YomiScan-Token"]});
    if (url.startsWith("http://127.0.0.1:50001")) throw new TypeError("Failed to fetch");  // the first engine exited
    return new Response("{}", {status: 200});
  }) as typeof fetch;
  try {
    const response = await localFetch("/api/v1/cache");
    assert.equal(response.status, 200);
    assert.deepEqual(requests, [{url: "http://127.0.0.1:50001/api/v1/cache", token: TOKEN},
      {url: "http://127.0.0.1:50002/api/v1/cache", token: TOKEN}]);
    assert.equal(starts, 2);
    assert.ok(polls >= 3, "each launch waited for initialization");
  } finally {
    g.chrome = saved.chrome; g.fetch = saved.fetch;
  }
});

test("Advanced shows what the local engine companion needs", async () => {
  const {companionSummary} = await import("../src/chapter/engine-controls");
  assert.equal(companionSummary({installed: false, ready: false, missing: []}), "Local engine: not installed.");
  assert.match(companionSummary({installed: false, ready: false, missing: []}, "a".repeat(32)),
    new RegExp(`installer asks for this extension's ID: ${"a".repeat(32)}`));
  assert.match(companionSummary({installed: true, ready: false, missing: ["dictionary"], version: "0.1.0"}),
    /^Local engine 0\.1\.0: installed; missing dictionary\. Run yomiscan-engine\.exe --prepare/);
  assert.match(companionSummary({installed: true, ready: true, missing: []}), /Automatic uses it first/);
  assert.match(companionSummary({installed: true, ready: false, missing: [], error: "OSError: x"}), /did not answer \(OSError: x\)/);
});

test("the local engine's download card states size, source and progress", () => {
  const status = {installed: true, ready: false, missing: ["dictionary"], bytes: 805e6, source: "huggingface.co/owner/models", prepare: null};
  const lines = companionSetupLines(status);
  assert.match(lines.size, /^805 MB, saved in your user folder/);
  assert.match(lines.source, /^From huggingface\.co\/owner\/models\. Each file is checked against a fingerprint/);
  assert.equal(companionProgress(status), "");
  assert.equal(companionProgress({...status, prepare: {state: "starting"}}), "Starting the download…");
  assert.equal(companionProgress({...status, prepare: {state: "running", loaded: 186e6, total: 805e6}}),
    "Downloading the local engine's models: 186 of 805 MB");
  assert.equal(companionProgress({...status, prepare: {state: "failed", error: "ValueError: bad hash"}}), "Download stopped: ValueError: bad hash");
  assert.deepEqual(parsePrepare({state: "running", loaded: 5, total: 10, pid: 3}), {state: "running", loaded: 5, total: 10, error: undefined});
  assert.equal(parsePrepare({state: "exploded"}), null);
  assert.equal(parsePrepare(null), null);
});
