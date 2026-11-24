// The browser engine (Stage 5a), hosted by the offscreen document: chooses WebGPU or WASM,
// installs pinned artifacts on request, and runs page vision without the Python backend.
import type * as Ort from 'onnxruntime-web';
import pinned from './artifact-manifest.json';
import {ArtifactStore, cacheStorage, componentBytes, parseManifest, type ArtifactComponent, type InstallProgress} from './artifacts';
import {MangaOcr, type OcrGeneration} from './vision-models';
import {recognizePage, type PageVision} from './vision';
import initLindera, {TokenizerBuilder} from 'lindera-wasm-unidic';
import sqlite3InitModule from '@sqlite.org/sqlite-wasm';
import {analyzeLexical, type JapaneseToken} from './lexical';
import {JmdictDatabase, fromLindera, toAnalysis, type LinderaToken, type Sqlite3} from './lexicon';
import type {Analysis} from '../api';

export type Backend = 'webgpu' | 'wasm';
export interface ComponentStatus {id: string; kind: string; variant: string; bytes: number; license: string; source: string; installed: boolean}
export interface EngineStatus {backend: Backend; isolated: boolean; threads: number; bundle: string; required: ComponentStatus[];
  install: {state: 'idle' | 'running' | 'failed' | 'done'; progress?: InstallProgress; error?: string}; loaded: boolean}

const manifest = parseManifest(pinned);

/** WebGPU when an adapter exists (q4 OCR, Stage 2: 85 ms per block); otherwise threaded WASM (int8). */
export async function chooseBackend(): Promise<Backend> {
  const gpu = (navigator as Navigator & {gpu?: {requestAdapter(): Promise<unknown>}}).gpu;
  try {return gpu && await gpu.requestAdapter() ? 'webgpu' : 'wasm';}
  catch {return 'wasm';}
}

/** The components one backend needs. int8 OCR must not run on WebGPU (no fast int8 path; 10x slower). */
export function requiredComponents(backend: Backend, components: readonly ArtifactComponent[] = manifest.components): ArtifactComponent[] {
  const ocr = backend === 'webgpu' ? 'q4' : 'int8';
  return components.filter(c => ['detector', 'tokenizer', 'dictionary'].includes(c.kind) || (c.kind === 'ocr' && c.variant === ocr));
}

interface LexicalEngine {tokenize(text: string): JapaneseToken[]; dictionary: JmdictDatabase}

export class BrowserEngine {
  private store = new ArtifactStore(cacheStorage);
  private backend: Promise<Backend> = chooseBackend();
  private install: EngineStatus['install'] = {state: 'idle'};
  private installing: AbortController | null = null;
  private vision: Promise<{ort: typeof Ort; detector: Ort.InferenceSession; ocr: MangaOcr}> | null = null;

  async status(): Promise<EngineStatus> {
    const backend = await this.backend;
    const required = await Promise.all(requiredComponents(backend).map(async c => ({id: c.id, kind: c.kind, variant: c.variant,
      bytes: componentBytes(c), license: c.license, source: c.source, installed: await this.store.installed(c)})));
    return {backend, isolated: crossOriginIsolated, threads: this.threads(), bundle: manifest.bundle, required,
      install: this.install, loaded: this.vision !== null || this.lexical !== null};
  }

  /** Start downloading the missing required components from `base` (explicit user action only). */
  startInstall(base: string): void {
    if (this.install.state === 'running') throw new Error('An installation is already running');
    this.installing = new AbortController();
    this.install = {state: 'running'};
    void (async () => {
      for (const component of requiredComponents(await this.backend))
        await this.store.install(component, base, progress => {this.install = {state: 'running', progress};}, this.installing!.signal);
    })().then(() => {this.install = {state: 'done'};},
      error => {console.warn('YomiScan browser engine install failed', error);
        this.install = {state: 'failed', error: error instanceof Error ? error.message : 'Installation failed'};});
  }

  cancelInstall(): void {this.installing?.abort();}

  async remove(): Promise<void> {
    if (this.install.state === 'running') throw new Error('Cancel the installation first');
    this.vision = null;
    const lexical = this.lexical;this.lexical = null;
    (await lexical?.catch(() => null))?.dictionary.close();
    for (const component of manifest.components) await this.store.remove(component);
    this.install = {state: 'idle'};
  }

  private threads(): number {return crossOriginIsolated ? Math.max(1, Math.min(navigator.hardwareConcurrency || 4, 8)) : 1;}

  private load() {
    this.vision ??= (async () => {
      const backend = await this.backend, components = requiredComponents(backend);
      for (const c of components) if (!await this.store.installed(c)) throw new Error('Browser engine models are not installed. Open Setup → Browser engine.');
      const ort: typeof Ort = await import(/* @vite-ignore */ chrome.runtime.getURL(backend === 'webgpu' ? 'ort/ort.webgpu.min.mjs' : 'ort/ort.wasm.min.mjs'));
      ort.env.wasm.wasmPaths = chrome.runtime.getURL('ort/');
      ort.env.wasm.numThreads = this.threads();
      const options: Ort.InferenceSession.SessionOptions = {executionProviders: [backend], graphOptimizationLevel: 'all'};
      if (backend === 'webgpu') options.preferredOutputLocation = 'cpu';
      const file = (component: ArtifactComponent, name: string) => {
        const entry = component.files.find(f => f.path.endsWith('/' + name));
        if (!entry) throw new Error(`Manifest component ${component.id} lacks ${name}`);
        return this.store.read(entry);
      };
      const detectorComponent = components.find(c => c.kind === 'detector')!, ocrComponent = components.find(c => c.kind === 'ocr')!;
      const detector = await ort.InferenceSession.create(await file(detectorComponent, 'detector-fp16.onnx'), options);
      const vocabulary = new TextDecoder().decode(await file(ocrComponent, 'vocab.txt')).split(/\r?\n/);
      if (vocabulary.at(-1) === '') vocabulary.pop();
      const generation = JSON.parse(new TextDecoder().decode(await file(ocrComponent, 'generation.json'))) as OcrGeneration;
      const ocr = new MangaOcr(ort, await ort.InferenceSession.create(await file(ocrComponent, 'encoder.onnx'), options),
        await ort.InferenceSession.create(await file(ocrComponent, 'decoder.onnx'), options), vocabulary, generation);
      return {ort, detector, ocr};
    })().catch(error => {this.vision = null; throw error;});
    return this.vision;
  }

  private lexical: Promise<LexicalEngine> | null = null;

  private loadLexical(): Promise<LexicalEngine> {
    this.lexical ??= (async () => {
      const components = requiredComponents(await this.backend);
      const component = (kind: string) => {
        const found = components.find(c => c.kind === kind);
        if (!found) throw new Error(`Manifest lacks the ${kind} component`);
        return found;
      };
      for (const kind of ['tokenizer', 'dictionary']) if (!await this.store.installed(component(kind)))
        throw new Error('Browser engine dictionary is not installed. Open Setup → Browser engine.');
      // lindera's JS glue is bundled; its WASM (with UniDic inside) is the pinned artifact.
      await initLindera({module_or_path: await this.store.read(component('tokenizer').files[0])});
      const builder = new TokenizerBuilder();
      builder.setDictionary('embedded://unidic'); builder.setMode('normal');
      const tokenizer = builder.build();
      const sqlite3 = await (sqlite3InitModule as unknown as (options: object) => Promise<Sqlite3>)({
        locateFile: () => chrome.runtime.getURL('sqlite/sqlite3.wasm'), print: () => {}, printErr: (m: string) => console.warn('sqlite3', m)});
      const dictionary = JmdictDatabase.open(sqlite3, await this.store.read(component('dictionary').files[0]));
      return {dictionary, tokenize: (text: string) => text.trim() ? (tokenizer.tokenize(text) as LinderaToken[]).map(fromLindera) : []};
    })().catch(error => {this.lexical = null; throw error;});
    return this.lexical;
  }

  /** Tokens, ranked JMdict entries, units, grammar notes and inflection labels, in the Study shape. */
  async analyzeText(text: string): Promise<Analysis> {
    const started = performance.now(), lexical = await this.loadLexical();
    const result = analyzeLexical(text, lexical.tokenize(text), form => lexical.dictionary.lookup(form));
    const analysis = toAnalysis(result, null, {analysis_origin: 'browser'});
    analysis.processing.analysis_ms = analysis.processing.total_ms = performance.now() - started;
    return analysis;
  }

  /** Detect, group, order and OCR one page image entirely in the browser. */
  async recognize(image: Blob, signal?: AbortSignal): Promise<PageVision & {load_ms: number}> {
    const started = performance.now(), models = await this.load(), load_ms = performance.now() - started;
    // Raw decoded pixels, as PIL reads them: no color management or alpha premultiplication.
    const bitmap = await createImageBitmap(image, {colorSpaceConversion: 'none', premultiplyAlpha: 'none'});
    try {
      const canvas = new OffscreenCanvas(bitmap.width, bitmap.height), context = canvas.getContext('2d', {willReadFrequently: true});
      if (!context) throw new Error('Cannot read page pixels');
      context.drawImage(bitmap, 0, 0);
      return {...await recognizePage(models, context.getImageData(0, 0, bitmap.width, bitmap.height), signal), load_ms};
    } finally {bitmap.close();}
  }
}
