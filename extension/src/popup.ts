import type { Analysis, Meaning } from "./api";
import { constrainPopup, popupPosition, resizePopup, type Point, type Rect, type ResizeEdge } from "./geometry";

export async function copyStudyText(text:string,write:(text:string)=>Promise<void>=value=>navigator.clipboard.writeText(value)):Promise<string> {
  try {await write(text);return 'Copied.';}
  catch {return 'Copy unavailable. Select the text and copy it manually.';}
}

export const styles = `
  :host { all: initial; color-scheme: light; }
  * { box-sizing: border-box; }
  .panel { font: 14px/1.5 system-ui, -apple-system, 'Segoe UI', sans-serif; color: #202b3a;
    background: #fffdf8; border: 1px solid #d9ddd7; border-radius: 14px; box-shadow: 0 12px 48px #0005;
    position: relative; display: flex; flex-direction: column; width: 100%; height: inherit;
    min-height: min(220px, calc(100vh - 16px)); max-height: inherit; overflow: hidden; text-align: left;
    overflow-wrap: anywhere; }
  .body { min-height: 0; overflow: auto; overscroll-behavior: contain; }
  header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;
    background: #edf4ee; border-bottom: 1px solid #d9ddd7; flex: none;
    cursor: grab; user-select: none; touch-action: none; }
  .dragging header { cursor: grabbing; }
  header strong { font-size: 15px; letter-spacing: .03em; }
  button { font: inherit; cursor: pointer; background: #fff; border: 1px solid #b8c7bc;
    border-radius: 7px; width: 30px; height: 30px; color: #263d2b; }
  button:focus-visible, summary:focus-visible, a:focus-visible { outline: 2px solid #287946; outline-offset: 2px; }
  button.copy, button.action { width:auto;height:auto;padding:4px 8px;margin-top:6px;font-size:12px; }
  button.action { margin:0 16px 12px; }
  .entry-divider { list-style:none;margin:8px 0 2px -20px;font-size:11px;color:#637366; }
  .copy-feedback { font-size:12px;color:#637366; }
  section { padding: 12px 16px; border-bottom: 1px solid #e8e9e2; }
  h2 { margin: 0 0 6px; font-size: 10px; letter-spacing: .13em; color: #637366; text-transform: uppercase; }
  p { margin: 4px 0; white-space: pre-wrap; }
  .original { font-size: 20px; line-height: 1.65; }
  .translation { font-size: 17px; line-height: 1.5; }
  .words { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr));
    gap: 0 20px; align-items: start; }
  article { min-width: 0; padding: 10px 0; border-bottom: 1px dashed #dedfd8; }
  .resize { position: absolute; touch-action: none; user-select: none; z-index: 2; }
  .resize-right { right: 0; top: 10px; bottom: 18px; width: 6px; cursor: ew-resize; }
  .resize-bottom { bottom: 0; left: 10px; right: 18px; height: 6px; cursor: ns-resize; }
  .resize-corner { bottom: 0; right: 0; width: 18px; height: 18px; cursor: nwse-resize;
    background: repeating-linear-gradient(135deg, transparent 0 3px, #7d9385 3px 5px, transparent 5px 7px);
    clip-path: polygon(100% 0, 100% 100%, 0 100%); }
  .surface { font-size: 18px; font-weight: 650; color: #244e34; }
  .metadata { font-size: 12px; color: #526071; }
  ul { margin: 5px 0; padding-left: 20px; }
  li { margin: 4px 0; }
  summary { cursor: pointer; color: #356348; font-size: 12px; }
  footer { padding: 12px 16px; font-size: 11px; color: #687268; }
  a { color: #356348; }
  .status { padding: 20px 16px; }
  .error { color: #9c302d; }
  .selection { position: fixed; inset: 0; cursor: crosshair; touch-action: none; user-select: none;
    background: #12251c26; font: 14px system-ui, sans-serif; }
  .hint { position: absolute; top: 18px; left: 50%; transform: translateX(-50%); max-width: 90%;
    background: #183b2f; color: white; padding: 10px 16px; border-radius: 8px; pointer-events: none; }
  .rectangle { position: absolute; border: 2px solid #5ff0a2; background: #ffffff20; pointer-events: none; }
`;

export function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, className?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function appendMeaning(list: HTMLElement, meaning: Meaning): void {
  const item = element("li", meaning.glosses.join("; "));
  const info: string[] = [];
  if (meaning.parts_of_speech.length) info.push(meaning.parts_of_speech.join(" / "));
  if (meaning.spellings.length || meaning.readings.length) info.push(`Only: ${[...meaning.spellings, ...meaning.readings].join(", ")}`);
  info.push(...meaning.labels, ...meaning.notes);
  if (info.length) item.append(element("div", info.join(" · "), "metadata"));
  list.append(item);
}

export class StudyPopup {
  private panel: HTMLDivElement;
  private body: HTMLDivElement;
  private manual: Rect | null = null;
  private listeners = new AbortController();
  private gesture: {pointerId: number; target: HTMLElement; start: Point; rect: Rect; kind: "drag" | ResizeEdge} | null = null;
  constructor(private host: HTMLElement, root: ShadowRoot, private anchor: Rect, close: () => void) {
    this.panel = element("div", undefined, "panel");
    this.panel.setAttribute("role", "dialog");
    this.panel.setAttribute("aria-label", "YomiScan study result");
    const header = element("header");
    header.append(element("strong", "YomiScan"));
    const button = element("button", "×");
    button.setAttribute("aria-label", "Close YomiScan");
    button.addEventListener("click", close);
    header.append(button);
    this.body = element("div", undefined, "body");
    this.body.setAttribute("aria-live", "polite");
    this.panel.append(header, this.body);
    this.bindHandle(header, "drag");
    for (const edge of ["right", "bottom", "corner"] as const) {
      const handle = element("div", undefined, `resize resize-${edge}`);
      handle.title = `Resize popup (${edge === "corner" ? "width and height" : edge === "right" ? "width" : "height"})`;
      this.bindHandle(handle, edge);
      this.panel.append(handle);
    }
    window.addEventListener("blur", () => this.endGesture(), {signal: this.listeners.signal});
    root.append(this.panel);
    this.position();
    button.focus({preventScroll: true});
  }

  position(): void {
    if (this.manual) {
      this.manual = constrainPopup(this.manual, {width: innerWidth, height: innerHeight});
      this.applyManual();
      return;
    }
    const size = {width: Math.max(1, Math.min(420, innerWidth - 16)), height: Math.max(1, Math.min(580, innerHeight - 16))};
    this.host.style.setProperty("width", `${size.width}px`, "important");
    this.host.style.setProperty("max-height", `${size.height}px`, "important");
    const measured = this.panel.getBoundingClientRect();
    const point = popupPosition(this.anchor, {width: size.width, height: Math.min(measured.height, size.height)}, {width: innerWidth, height: innerHeight});
    this.host.style.setProperty("left", `${point.x}px`, "important");
    this.host.style.setProperty("top", `${point.y}px`, "important");
  }

  private applyManual(): void {
    if (!this.manual) return;
    for (const [property, value] of Object.entries({left: this.manual.x, top: this.manual.y,
      width: this.manual.width, height: this.manual.height, "max-height": this.manual.height})) {
      this.host.style.setProperty(property, `${value}px`, "important");
    }
  }

  private bindHandle(handle: HTMLElement, kind: "drag" | ResizeEdge): void {
    const options = {signal: this.listeners.signal};
    handle.addEventListener("pointerdown", event => {
      if (event.button !== 0 || !event.isPrimary || this.gesture
        || (event.target instanceof Element && event.target.closest("button"))) return;
      event.preventDefault();
      const bounds = this.panel.getBoundingClientRect();
      this.manual = constrainPopup({x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height},
        {width: innerWidth, height: innerHeight});
      this.gesture = {pointerId: event.pointerId, target: handle, start: {x: event.clientX, y: event.clientY},
        rect: {...this.manual}, kind};
      handle.setPointerCapture(event.pointerId);
      this.panel.classList.toggle("dragging", kind === "drag");
      this.applyManual();
    }, options);
    handle.addEventListener("pointermove", event => {
      const gesture = this.gesture;
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      const delta = {x: event.clientX - gesture.start.x, y: event.clientY - gesture.start.y};
      const viewport = {width: innerWidth, height: innerHeight};
      this.manual = gesture.kind === "drag"
        ? constrainPopup({...gesture.rect, x: gesture.rect.x + delta.x, y: gesture.rect.y + delta.y}, viewport)
        : constrainPopup(resizePopup(gesture.rect, delta, gesture.kind, viewport), viewport);
      this.applyManual();
    }, options);
    for (const name of ["pointerup", "pointercancel", "lostpointercapture"] as const) {
      handle.addEventListener(name, event => {
        if (event.pointerId === this.gesture?.pointerId) this.endGesture();
      }, options);
    }
  }

  private endGesture(): void {
    const gesture = this.gesture;
    this.gesture = null;
    this.panel.classList.remove("dragging");
    if (gesture?.target.hasPointerCapture(gesture.pointerId)) gesture.target.releasePointerCapture(gesture.pointerId);
  }

  dispose(): void {
    this.endGesture();
    this.listeners.abort();
  }

  /** Ranked candidates, best first: the best entry's first senses, the rest folded so another
   * word's senses never appear as if they belonged to this one. */
  private appendMeanings(row: HTMLElement, meanings: Meaning[]): void {
    const best = meanings.filter(meaning => meaning.entry_id === meanings[0]?.entry_id);
    const others = meanings.slice(best.length);
    const list = element("ul");
    best.slice(0, 3).forEach(meaning => appendMeaning(list, meaning));
    row.append(list);
    const folded = best.slice(3).length, otherEntries = new Set(others.map(meaning => meaning.entry_id)).size;
    if (!folded && !otherEntries) return;
    const details = element("details");
    details.append(element("summary", [folded ? `${folded} more senses` : "",
      otherEntries ? `${otherEntries} other dictionary ${otherEntries === 1 ? "entry" : "entries"}` : ""].filter(Boolean).join(" · ")));
    const more = element("ul");
    best.slice(3).forEach(meaning => appendMeaning(more, meaning));
    let entry: number | null = null;
    for (const meaning of others) {
      if (meaning.entry_id !== entry) { entry = meaning.entry_id; more.append(element("li", "Other entry", "entry-divider")); }
      appendMeaning(more, meaning);
    }
    details.append(more);
    details.addEventListener("toggle", () => this.position());
    row.append(details);
  }

  status(message: string, error = false): void {
    this.body.replaceChildren(element("p", message, `status${error ? " error" : ""}`));
    this.position();
  }

  show(data: Analysis): void {
    this.body.replaceChildren();
    const target=data.target_language??'en',targetName=['pt-BR','por_Latn'].includes(target)?'Portuguese':
      ['es','spa_Latn'].includes(target)?'Spanish':'English';
    // Dedicated original section is the future OCR-edit hook; read-only in Phase 4.
    for (const [title, text, className] of [
      ["Original", data.original_text || "No text was recognized. Try a clearer crop.", "original"],
      [targetName==='English'?"Translation":targetName+" translation (experimental)", data.translation ?? "No sentence translation available.", "translation"],
    ]) {
      const section = element("section");
      section.append(element("h2", title), element("p", text, className));
      const value=className==="original"?data.original_text:data.translation;
      const copy=element('button',className==="original"?'Copy Japanese':'Copy '+targetName,'copy');
      copy.setAttribute('aria-label',className==="original"?'Copy original Japanese':'Copy '+targetName+' sentence translation');
      copy.lang='en';
      copy.disabled=!value;
      const feedback=element('p','','copy-feedback');feedback.setAttribute('role','status');
      feedback.lang='en';
      copy.addEventListener('click',()=>{void copyStudyText(value??'').then(message=>{
        if(this.listeners.signal.aborted || !section.isConnected)return;
        feedback.textContent=message;
        window.setTimeout(()=>{if(feedback.textContent===message)feedback.textContent='';},3000);
      });});
      section.append(copy,feedback);
      if (className === "original") section.lang = "ja";
      this.body.append(section);
    }
    const units = data.units ?? [];
    if (units.length) {
      // Multi-word expressions first: their meaning differs from their parts (かもしれない).
      const expressions = element("section");
      expressions.append(element("h2", "Expressions"));
      const list = element("div", undefined, "words");
      for (const unit of units) {
        const row = element("article");
        const surface = element("div", unit.surface, "surface");
        surface.lang = "ja";
        row.append(surface);
        if (unit.dictionary_form !== unit.surface) row.append(element("p", `Dictionary form: ${unit.dictionary_form}`, "metadata"));
        const parts = data.tokens.slice(unit.start_token, unit.end_token).map(token => token.surface);
        row.append(element("p", `Words: ${parts.join(" + ")}`, "metadata"));
        this.appendMeanings(row, unit.meanings);
        list.append(row);
      }
      expressions.append(list);
      this.body.append(expressions);
    }
    const breakdown = element("section");
    if(targetName!=='English')breakdown.append(element('p','Dictionary definitions remain English.'));
    breakdown.append(element("h2", "Word breakdown"));
    const words = element("div", undefined, "words");
    breakdown.append(words);
    const tokens = data.tokens.filter(token => !/^[\p{P}\p{S}\s]+$/u.test(token.surface));
    if (!tokens.length) breakdown.append(element("p", "No word breakdown available."));
    for (const token of tokens) {
      const row = element("article");
      const surface = element("div", token.surface, "surface");
      surface.lang = "ja";
      row.append(surface, element("p", `Reading: ${token.reading ?? "unavailable"}`, "metadata"));
      row.append(element("p", `Lemma: ${token.lemma ?? "unavailable"}`, "metadata"));
      if (token.dictionary_form && token.dictionary_form !== token.lemma) row.append(element("p", `Dictionary form: ${token.dictionary_form}`, "metadata"));
      row.append(element("p", `POS: ${token.part_of_speech ?? "unavailable"}`, "metadata"));
      if (token.conjugation_type || token.conjugation_form) row.append(element("p", `Conjugation: ${[token.conjugation_type, token.conjugation_form].filter(Boolean).join(" / ")}`, "metadata"));
      if (!token.meanings.length) row.append(element("p", "No dictionary match", "metadata"));
      this.appendMeanings(row, token.meanings);
      words.append(row);
    }
    this.body.append(breakdown);
    const footer = element("footer");
    footer.append(element("p", "Dictionary candidates ranked by the word's form and grammar; the context-specific meaning is not checked."));
    const study = data.provenance?.study_ocr as {mode?: unknown; blocks?: unknown; reason?: unknown} | undefined;
    if (study?.mode === "blocks" && typeof study.blocks === "number")
      footer.append(element("p", `Read ${study.blocks} text blocks separately, in reading order (one line each).`));
    else if (study?.reason === "detector_unavailable" || study?.reason === "detector_failed")
      footer.append(element("p", "Text detector unavailable: the selection was read as one block, so text from several bubbles may be missing."));
    const attribution = element("a", "JMdict © EDRDG — CC BY-SA 4.0");
    attribution.href = "https://www.edrdg.org/edrdg/licence.html";
    attribution.target = "_blank"; attribution.rel = "noopener noreferrer";
    footer.append(attribution);
    const time = data.processing;
    if(data.provenance?.analysis_origin==='page')footer.append(element('p','Reused completed page analysis; no new screenshot or OCR.'));
    footer.append(element("p", `Local processing · OCR ${Math.round(time.ocr_ms)} ms · Translation ${Math.round(time.translation_ms)} ms · Analysis ${Math.round(time.analysis_ms)} ms`));
    this.body.append(footer);
    const save=element('button','Save to History','action'),saved=element('p','','copy-feedback');saved.setAttribute('role','status');
    save.addEventListener('click',()=>{save.disabled=true;void chrome.runtime.sendMessage({type:'study-history',operation:'save',payload:{analysis:data}}).then(reply=>{
      if(!this.listeners.signal.aborted)saved.textContent=reply?.ok?'Saved locally.':reply?.error??'History unavailable.';
    },()=>{if(!this.listeners.signal.aborted)saved.textContent='History unavailable. Reload the extension.';}).finally(()=>{save.disabled=false;});});
    this.body.append(save,saved);
    this.position();
  }
}
