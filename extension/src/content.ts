import { parseAnalysis } from "./api";
import { sameViewport, selectionRect, validSelection, type Point, type Rect, type Viewport } from "./geometry";
import { element, StudyPopup, styles } from "./popup";

const globalState = globalThis as typeof globalThis & { __yomiscanInstalled?: boolean };
if (!globalState.__yomiscanInstalled) {
  globalState.__yomiscanInstalled = true;
  install();
}

function viewport(): Viewport {
  return {width: innerWidth, height: innerHeight, scrollX, scrollY, scale: visualViewport?.scale ?? 1};
}

function install(): void {
  let id: string | null = null;
  let host: HTMLDivElement | null = null;
  let root: ShadowRoot | null = null;
  let popup: StudyPopup | null = null;
  let lifecycle = new AbortController();
  let selection = new AbortController();
  let mode: "selecting" | "capturing" | "processing" | "result" = "result";
  let captureViewport = viewport();
  let anchor: Rect = {x: 16, y: 16, width: 0, height: 0};
  let previousFocus: HTMLElement | null = null;

  function close(): void {
    if (id) void chrome.runtime.sendMessage({type: "cancel", id}).catch(() => {});
    id = null;
    selection.abort(); lifecycle.abort();
    popup?.dispose();
    host?.remove(); host = null; root = null; popup = null;
    if (previousFocus?.isConnected) previousFocus.focus({preventScroll: true});
    previousFocus = null;
  }

  function openPopup(): StudyPopup {
    host!.style.removeProperty("inset");
    host!.style.removeProperty("visibility");
    if (!popup) {
      host!.style.setProperty("height", "auto", "important");
      popup = new StudyPopup(host!, root!, anchor, close);
    }
    return popup;
  }

  function start(): void {
    close();
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    lifecycle = new AbortController(); selection = new AbortController();
    id = crypto.randomUUID(); mode = "selecting";
    host = element("div");
    for (const [key, value] of Object.entries({all: "initial", position: "fixed", inset: "0", "z-index": "2147483647", display: "block", margin: "0", padding: "0", border: "0"})) host.style.setProperty(key, value, "important");
    root = host.attachShadow({mode: "closed"});
    for (const eventName of ["pointerdown", "pointermove", "pointerup", "click", "dblclick"]) {
      host.addEventListener(eventName, event => event.stopPropagation(), {signal: lifecycle.signal});
    }
    root.append(element("style", styles));
    document.documentElement.append(host);
    const layer = element("div", undefined, "selection");
    layer.tabIndex = -1;
    layer.setAttribute("aria-label", "Drag around Japanese text. Escape cancels.");
    const hint = element("div", "Drag around Japanese text · Esc to cancel", "hint");
    const box = element("div", undefined, "rectangle");
    box.hidden = true;
    layer.append(hint, box); root.append(layer); layer.focus({preventScroll: true});
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); close(); }
      else if (mode === "selecting" || mode === "capturing") { event.preventDefault(); event.stopImmediatePropagation(); }
    }, {capture: true, signal: lifecycle.signal});
    window.addEventListener("scroll", () => {
      if (mode === "selecting" || mode === "capturing") close();
    }, {capture: true, signal: lifecycle.signal});
    window.addEventListener("resize", () => {
      if (mode === "selecting" || mode === "capturing") close(); else popup?.position();
    }, {signal: lifecycle.signal});
    document.addEventListener("visibilitychange", () => { if (document.hidden) close(); }, {signal: lifecycle.signal});
    window.addEventListener("pagehide", close, {signal: lifecycle.signal});
    layer.addEventListener("wheel", event => event.preventDefault(), {passive: false, signal: selection.signal});
    layer.addEventListener("contextmenu", event => event.preventDefault(), {signal: selection.signal});
    let startPoint: Point | null = null;
    const move = (event: PointerEvent) => {
      if (!startPoint) return;
      anchor = selectionRect(startPoint, {x: event.clientX, y: event.clientY}, viewport());
      Object.assign(box.style, {left: `${anchor.x}px`, top: `${anchor.y}px`, width: `${anchor.width}px`, height: `${anchor.height}px`});
      box.hidden = false;
    };
    layer.addEventListener("pointerdown", event => {
      if (event.button !== 0 || !event.isPrimary) return;
      event.preventDefault(); event.stopPropagation();
      startPoint = {x: event.clientX, y: event.clientY};
      layer.setPointerCapture(event.pointerId); move(event);
    }, {signal: selection.signal});
    layer.addEventListener("pointermove", move, {signal: selection.signal});
    layer.addEventListener("pointercancel", close, {signal: selection.signal});
    layer.addEventListener("pointerup", async event => {
      if (!startPoint || event.button !== 0) return;
      move(event); startPoint = null;
      captureViewport = viewport();
      if (!validSelection(anchor, captureViewport)) { box.hidden = true; hint.textContent = "Select a larger region · Esc to cancel"; return; }
      selection.abort(); layer.remove();
      const requestId = id;
      mode = "capturing";
      host!.style.setProperty("visibility", "hidden", "important");
      // Let Chrome paint away the overlay before asking the worker for a screenshot.
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      if (id !== requestId) return;
      try {
        const reply = await chrome.runtime.sendMessage({type: "capture", id, rect: anchor, viewport: captureViewport});
        if (id !== requestId) return;
        mode = "result";
        if (!reply?.ok) throw new Error(reply?.error || "Screenshot analysis failed. Please try again.");
        openPopup().show(parseAnalysis(reply.data));
      } catch (error) {
        if (id !== requestId) return;
        mode = "result";
        openPopup().status(error instanceof Error ? error.message : "YomiScan could not analyze this crop.", true);
      }
    }, {signal: selection.signal});
  }

  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id) return;
    if (message?.type === "activate") { start(); respond(true); }
    if (message?.type === "verify-capture") respond(id === message.id && mode === "capturing" && sameViewport(captureViewport, viewport()) && !document.hidden);
    if (message?.type === "captured" && id === message.id) {
      mode = "processing";
      openPopup().status("Reading and translating locally…");
      respond(true);
    }
  });
}
