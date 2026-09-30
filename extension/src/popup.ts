import type { Analysis, Meaning } from "./api";
import { constrainPopup, popupPosition, resizePopup, type Point, type Rect, type ResizeEdge } from "./geometry";

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

  status(message: string, error = false): void {
    this.body.replaceChildren(element("p", message, `status${error ? " error" : ""}`));
    this.position();
  }

  show(data: Analysis): void {
    this.body.replaceChildren();
    // Dedicated original section is the future OCR-edit hook; read-only in Phase 4.
    for (const [title, text, className] of [
      ["Original", data.original_text || "No text was recognized. Try a clearer crop.", "original"],
      ["Translation", data.translation ?? "No sentence translation available.", "translation"],
    ]) {
      const section = element("section");
      section.append(element("h2", title), element("p", text, className));
      if (className === "original") section.lang = "ja";
      this.body.append(section);
    }
    const breakdown = element("section");
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
      const list = element("ul");
      token.meanings.slice(0, 3).forEach(meaning => appendMeaning(list, meaning));
      row.append(list);
      if (token.meanings.length > 3) {
        const details = element("details");
        details.append(element("summary", `${token.meanings.length - 3} more dictionary senses`));
        const more = element("ul");
        token.meanings.slice(3).forEach(meaning => appendMeaning(more, meaning));
        details.append(more);
        details.addEventListener("toggle", () => this.position());
        row.append(details);
      }
      words.append(row);
    }
    this.body.append(breakdown);
    const footer = element("footer");
    footer.append(element("p", "Dictionary candidates; meanings are not selected for this context."));
    const attribution = element("a", "JMdict © EDRDG — CC BY-SA 4.0");
    attribution.href = "https://www.edrdg.org/edrdg/licence.html";
    attribution.target = "_blank"; attribution.rel = "noopener noreferrer";
    footer.append(attribution);
    const time = data.processing;
    footer.append(element("p", `Local processing · OCR ${Math.round(time.ocr_ms)} ms · Translation ${Math.round(time.translation_ms)} ms · Analysis ${Math.round(time.analysis_ms)} ms`));
    this.body.append(footer);
    this.position();
  }
}
