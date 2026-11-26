// The browser engine (Stage 5a), hosted by the offscreen document: chooses WebGPU or WASM,
// installs pinned artifacts on request, and runs page vision without the Python backend.
import type * as Ort from 'onnxruntime-web';
import pinned from './artifact-manifest.json';
import {ArtifactStore, cacheStorage, componentBytes, parseManifest, type ArtifactComponent, type InstallProgress} from './artifacts';
import {MangaOcr, type OcrGeneration} from './vision-models';
import {detectBlocks, recognizeBlocks, recognizePage, type PageVision} from './vision';
import type {Box} from './geometry';
import initLindera, {TokenizerBuilder} from 'lindera-wasm-unidic';
import sqlite3InitModule from '@sqlite.org/sqlite-wasm';
import {analyzeLexical, type JapaneseToken} from './lexical';
import {JmdictDatabase, fromLindera, toAnalysis, type LinderaToken, type Sqlite3} from './lexicon';
import type {Analysis} from '../api';
import {Tokenizer} from '@huggingface/tokenizers';
import {OpusTranslator, type MarianTokenizer} from './translation';

export type Backend = 'webgpu' | 'wasm';
export interface ComponentStatus {id: string; kind: string; variant: string; bytes: number; license: string; source: string; installed: boolean}
export interface EngineStatus {backend: Backend; isolated: boolean; threads: number; bundle: string; required: ComponentStatus[];
  install: {state: 'idle' | 'running' | 'failed' | 'done'; progress?: InstallProgress; error?: string}; loaded: boolean;
  /** Bytes still to download for this device, and what Chrome reports for this extension's storage. */
  missingBytes: number; storage: {usage: number; quota: number} | null; persisted: boolean}

/** Extra room kept free beyond the download itself: Cache Storage overhead and the rest of the disk. */
export const STORAGE_MARGIN = 256 * 2 ** 20;

/** Refuse a download that cannot fit, before any byte is fetched. */
export function storageShortfall(missing: number, storage: {usage: number; quota: number} | null): string | null {
  if (!storage || missing === 0) return null;
  const free = storage.quota - storage.usage, mb = (bytes: number) => Math.ceil(bytes / 1e6);
  return free < missing + STORAGE_MARGIN ? `Not enough free space: the models need ${mb(missing)} MB and Chrome reports ${mb(Math.max(0, free))} MB ` +
    `available. Free at least ${mb(missing + STORAGE_MARGIN - free)} MB of disk space, then download again.` : null;
}

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
  return components.filter(c => ['detector', 'dictionary', 'translation'].includes(c.kind) || (c.kind === 'ocr' && c.variant === ocr));
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
      install: this.install, loaded: this.vision !== null || this.lexical !== null,
      missingBytes: required.reduce((n, c) => n + (c.installed ? 0 : c.bytes), 0), storage: await this.storage(),
      persisted: await navigator.storage.persisted()};
  }

  private async storage(): Promise<{usage: number; quota: number} | null> {
    const {usage, quota} = await navigator.storage.estimate();
    return usage === undefined || quota === undefined ? null : {usage, quota};
  }

  /** Start downloading the missing required components from `base` (explicit user action only).
   * A download that cannot fit is refused first; persistence keeps Chrome from evicting the models. */
  async startInstall(base: string): Promise<void> {
    if (this.install.state === 'running') throw new Error('An installation is already running');
    this.install = {state: 'running'};  // claimed before any await, so a second click is refused
    const {missingBytes, storage} = await this.status();
    const shortfall = storageShortfall(missingBytes, storage);
    if (shortfall) {this.install = {state: 'failed', error: shortfall}; return;}
    await navigator.storage.persist();
    this.installing = new AbortController();
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
    this.vision = null;this.translator = null;
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
      const ort = await this.runtime();
      const options: Ort.InferenceSession.SessionOptions = {executionProviders: [backend], graphOptimizationLevel: 'all'};
      if (backend === 'webgpu') options.preferredOutputLocation = 'cpu';
      const file = (component: ArtifactComponent, name: string) => this.file(component, name);
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

  private ortRuntime: Promise<typeof Ort> | null = null;
  /** One ONNX Runtime bundle per document: the WebGPU build (it also runs WASM) or the plain threaded WASM build. */
  private runtime(): Promise<typeof Ort> {
    this.ortRuntime ??= (async () => {
      const backend = await this.backend;
      const ort: typeof Ort = await import(/* @vite-ignore */ chrome.runtime.getURL(backend === 'webgpu' ? 'ort/ort.webgpu.min.mjs' : 'ort/ort.wasm.min.mjs'));
      ort.env.wasm.wasmPaths = chrome.runtime.getURL('ort/');
      ort.env.wasm.numThreads = this.threads();
      return ort;
    })().catch(error => {this.ortRuntime = null; throw error;});
    return this.ortRuntime;
  }

  private file(component: ArtifactComponent, name: string): Promise<Uint8Array<ArrayBuffer>> {
    const entry = component.files.find(f => f.path.endsWith('/' + name));
    if (!entry) throw new Error(`Manifest component ${component.id} lacks ${name}`);
    return this.store.read(entry);
  }

  private translator: Promise<OpusTranslator> | null = null;
  /** OPUS-MT always runs on WASM threads: Stage 2 found WebGPU slower for this decoder and less exact (93/100). */
  private loadTranslator(): Promise<OpusTranslator> {
    this.translator ??= (async () => {
      const component = requiredComponents(await this.backend).find(c => c.kind === 'translation');
      if (!component || !await this.store.installed(component)) throw new Error('Browser engine translation model is not installed. Open Setup → Browser engine.');
      const ort = await this.runtime(), json = async (name: string) => JSON.parse(new TextDecoder().decode(await this.file(component, name)));
      const options: Ort.InferenceSession.SessionOptions = {executionProviders: ['wasm'], graphOptimizationLevel: 'all'};
      const tokenizer = new Tokenizer(await json('tokenizer.json'), await json('tokenizer_config.json')) as unknown as MarianTokenizer;
      return new OpusTranslator(ort, tokenizer, await ort.InferenceSession.create(await this.file(component, 'encoder_model_fp16.onnx'), options),
        await ort.InferenceSession.create(await this.file(component, 'decoder_model_merged_fp16.onnx'), options),
        await json('config.json'), await json('generation_config.json'));
    })().catch(error => {this.translator = null; throw error;});
    return this.translator;
  }

  /** Sentence translation, one line at a time (as the backend's single-line path). */
  async translate(text: string): Promise<{translation: string; ms: number}> {
    const started = performance.now(), translator = await this.loadTranslator();
    return {translation: await translator.translate(text), ms: performance.now() - started};
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
      if (!await this.store.installed(component('dictionary')))
        throw new Error('Browser engine dictionary is not installed. Open Setup → Browser engine.');
      // lindera's JS glue is bundled and its WASM (with UniDic inside) ships with the extension:
      // the store allows no remotely loaded code. Same pinned npm package, same bytes as before.
      await initLindera({module_or_path: chrome.runtime.getURL('lindera/lindera_wasm_unidic_bg.wasm')});
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

  /** Tokens, ranked JMdict entries, units, grammar notes, inflection labels and (optionally) the
   * sentence translation, in the Study response shape. */
  async analyzeText(text: string, {translate = false} = {}): Promise<Analysis> {
    const started = performance.now(), lexical = await this.loadLexical();
    const result = analyzeLexical(text, lexical.tokenize(text), form => lexical.dictionary.lookup(form));
    const analysis_ms = performance.now() - started;
    const translated = translate && text.trim() ? await this.translate(text) : null;
    const analysis = toAnalysis(result, translated?.translation ?? null,
      {analysis_origin: 'browser', ...(translated ? {engine: 'marian-mt', model: 'Helsinki-NLP/opus-mt-ja-en'} : {})});
    analysis.processing.analysis_ms = analysis_ms;
    analysis.processing.translation_ms = translated?.ms ?? 0;
    analysis.processing.total_ms = performance.now() - started;
    return analysis;
  }

  /** Detect, group, order and OCR one page image entirely in the browser. */
  async recognize(image: Blob, signal?: AbortSignal): Promise<PageVision & {load_ms: number}> {
    const started = performance.now(), models = await this.load(), load_ms = performance.now() - started;
    return {...await recognizePage(models, await pixels(image), signal), load_ms};
  }

  /** Reading mode: the page as /api/v1/analyze-page returns it, so the reading layer is unchanged. */
  async readPage(image: Blob, signal?: AbortSignal): Promise<PageResponse> {
    const started = performance.now(), vision = await this.recognize(image, signal);
    let analysis_ms = 0, translation_ms = 0;
    const text_blocks: PageBlock[] = [];
    for (const block of vision.blocks) {
      signal?.throwIfAborted();
      const base: PageBlock = {id: block.id, region_ids: block.regionIds, bbox: block.bbox, orientation: block.orientation,
        reading_order: block.readingOrder, original_text: block.text, translation: null, tokens: [], units: [], grammar: [],
        confidence: block.confidence, category: 'unknown', status: block.status, error_message: block.error, provenance: {}};
      if (block.status !== 'success') {text_blocks.push(base); continue;}
      try {
        const analysis = await this.analyzeText(block.text, {translate: true});
        analysis_ms += analysis.processing.analysis_ms; translation_ms += analysis.processing.translation_ms;
        text_blocks.push({...base, translation: analysis.translation, tokens: analysis.tokens, units: analysis.units ?? [],
          grammar: analysis.grammar ?? [], provenance: {engine: 'marian-mt', model: OPUS_MODEL, engine_kind: 'browser'}});
      } catch (error) {
        // As the backend: a failed block reports its own error; the page continues.
        console.warn('YomiScan browser analysis failed for block', block.id, error);
        text_blocks.push({...base, status: 'error', error_message: 'Text analysis failed for this block.'});
      }
    }
    return {width: vision.width, height: vision.height, regions_detected: vision.regions, regions_filtered: vision.filtered, text_blocks,
      processing: {detection_ms: vision.timings.detection_ms, ocr_ms: vision.timings.ocr_ms, translation_ms, analysis_ms,
        total_ms: performance.now() - started}};
  }

  /** Study a selection as ImageAnalysisService.analyze_image does: with two or more detected
   * blocks, read each block separately in reading order; otherwise read the whole selection. */
  async study(image: Blob): Promise<Analysis> {
    const started = performance.now(), models = await this.load(), data = await pixels(image);
    const {blocks} = await detectBlocks(models, data);
    let ocr_ms = 0;
    if (blocks.length >= 2) {
      const t = performance.now(), recognized = (await recognizeBlocks(models, data, blocks)).filter(b => b.status === 'success');
      ocr_ms = performance.now() - t;
      if (recognized.length) {
        const parts = [];
        for (const block of recognized) parts.push(await this.analyzeText(block.text, {translate: true}));
        const combined = combineAnalyses(parts);
        combined.provenance = {...combined.provenance, study_ocr: {mode: 'blocks', blocks: recognized.length}};
        combined.processing = {...combined.processing, ocr_ms, total_ms: performance.now() - started};
        return combined;
      }
    }
    const t = performance.now(), text = await models.ocr.recognize(data.data, data.width, data.height);
    ocr_ms += performance.now() - t;
    const analysis = await this.analyzeText(text, {translate: true});
    analysis.provenance = {...analysis.provenance, study_ocr: {mode: 'selection', blocks: blocks.length,
      ...(blocks.length >= 2 ? {reason: 'no_japanese_blocks'} : {})}};
    analysis.processing = {...analysis.processing, ocr_ms, total_ms: performance.now() - started};
    return analysis;
  }
}

const OPUS_MODEL = 'Helsinki-NLP/opus-mt-ja-en';
export interface PageBlock {id: number; region_ids: number[]; bbox: Box; orientation: string; reading_order: number; original_text: string;
  translation: string | null; tokens: Analysis['tokens']; units: NonNullable<Analysis['units']>; grammar: NonNullable<Analysis['grammar']>;
  confidence: number | null; category: string; status: string; error_message: string | null; provenance: Record<string, unknown>}
export interface PageResponse {width: number; height: number; regions_detected: number; regions_filtered: number; text_blocks: PageBlock[];
  processing: {detection_ms: number; ocr_ms: number; translation_ms: number; analysis_ms: number; total_ms: number}}

/** Raw decoded pixels, as PIL reads them: no color management or alpha premultiplication. */
async function pixels(image: Blob): Promise<ImageData> {
  const bitmap = await createImageBitmap(image, {colorSpaceConversion: 'none', premultiplyAlpha: 'none'});
  try {
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height), context = canvas.getContext('2d', {willReadFrequently: true});
    if (!context) throw new Error('Cannot read page pixels');
    context.drawImage(bitmap, 0, 0);
    return context.getImageData(0, 0, bitmap.width, bitmap.height);
  } finally {bitmap.close();}
}

/** analysis.analyze_recognized_blocks: texts and translations joined by newlines, tokens in
 * block order, unit and grammar spans shifted into the combined token sequence. */
export function combineAnalyses(parts: readonly Analysis[]): Analysis {
  const units: NonNullable<Analysis['units']> = [], grammar: NonNullable<Analysis['grammar']> = [];
  let offset = 0;
  for (const part of parts) {
    units.push(...(part.units ?? []).map(u => ({...u, start_token: u.start_token + offset, end_token: u.end_token + offset})));
    grammar.push(...(part.grammar ?? []).map(g => ({...g, start_token: g.start_token + offset, end_token: g.end_token + offset})));
    offset += part.tokens.length;
  }
  const translations = parts.map(p => p.translation);
  const sum = (key: 'ocr_ms' | 'translation_ms' | 'analysis_ms' | 'total_ms') => parts.reduce((n, p) => n + p.processing[key], 0);
  return {...parts[0], original_text: parts.map(p => p.original_text).join('\n'),
    translation: translations.every(t => t !== null) ? translations.join('\n') : null,
    tokens: parts.flatMap(p => p.tokens), units, grammar,
    processing: {ocr_ms: sum('ocr_ms'), translation_ms: sum('translation_ms'), analysis_ms: sum('analysis_ms'), total_ms: sum('total_ms')}};
}
