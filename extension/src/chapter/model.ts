export type PageState = "queued" | "processing" | "translated" | "failed" | "skipped";
export type ViewMode = "original" | "english";
export interface PageRecord<T, R> {
  id: number; key: object; identity: string; source: T; state: PageState;
  result?: R; error?: string; attempts: number; cancelled?: boolean; deferred?: boolean;
}
export class SkipPage extends Error {}
export class WaitForViewport extends SkipPage {}

/** Recomputed before every job: visible, next, previous, then distant pages. */
export function viewportPriority(top: number, bottom: number, height: number): number {
  if (bottom > 0 && top < height) return 0;
  if (top >= height && top < height * 2) return 1 + (top-height)/height;
  if (bottom <= 0 && bottom > -height) return 3 + (-bottom)/height;
  return 5 + Math.min(Math.abs(top-height), Math.abs(bottom))/height;
}

export interface QueueHooks<T, R> {
  process(page: PageRecord<T, R>, signal: AbortSignal): Promise<R>;
  priority(page: PageRecord<T, R>): number;
  release(result: R): void;
  changed(): void;
}

/** One job at a time matches the backend's single owning inference thread. */
export class ChapterQueue<T, R> {
  readonly pages = new Map<object, PageRecord<T, R>>();
  active = false;
  view: ViewMode = "english";
  private nextId = 1;
  private controller: AbortController | null = null;
  private running: Promise<void> | null = null;
  private disposed = false;
  constructor(private readonly hooks: QueueHooks<T, R>) {}

  register(key: object, identity: string, source: T): PageRecord<T, R> {
    const previous = this.pages.get(key);
    if (previous?.identity === identity) { previous.source = source; return previous; }
    if (previous?.result) this.hooks.release(previous.result);
    const page: PageRecord<T, R> = {id: previous?.id ?? this.nextId++, key, identity, source,
      state: "queued", attempts: 0};
    this.pages.set(key, page);
    this.hooks.changed(); this.schedule();
    return page;
  }
  remove(key: object): void {
    const page = this.pages.get(key);
    if (page?.result) this.hooks.release(page.result);
    this.pages.delete(key); this.hooks.changed();
  }
  start(): void {
    if (this.disposed) return;
    this.active = true;
    for (const page of this.pages.values()) if (page.cancelled) {
      page.state = "queued"; page.cancelled = false; page.error = undefined;
    }
    this.hooks.changed(); this.schedule();
  }
  stop(): void {
    this.active = false;
    for (const page of this.pages.values()) if (page.state === "queued") {
      page.state = "skipped"; page.cancelled = true; page.error = "Stopped before processing";
    }
    // Already submitted inference may finish; its result is retained for toggling.
    this.hooks.changed();
  }
  retry(): void {
    for (const page of this.pages.values()) if (page.state === "failed" || page.state === "skipped") {
      page.state = "queued"; page.error = undefined; page.cancelled = false;
    }
    this.start();
  }
  visible(key:object):void {
    const page=this.pages.get(key);
    if(this.active && page?.state==="skipped" && page.deferred && page.attempts<3) {
      page.deferred=false;page.state="queued";page.error=undefined;this.hooks.changed();this.schedule();
    }
  }
  setView(view: ViewMode): void { this.view = view; this.hooks.changed(); }
  async idle(): Promise<void> { await this.running; }
  dispose(): void {
    this.disposed = true; this.active = false; this.controller?.abort();
    for (const page of this.pages.values()) if (page.result) this.hooks.release(page.result);
    this.pages.clear(); this.hooks.changed();
  }
  private schedule(): void {
    if (!this.active || this.running || this.disposed) return;
    // Defer until a discovery batch has registered every candidate.
    this.running = Promise.resolve().then(() => this.drain()).finally(() => {
      this.running = null;
      if(this.active && [...this.pages.values()].some(p=>p.state==="queued"))this.schedule();
    });
  }
  private async drain(): Promise<void> {
    while (this.active && !this.disposed) {
      const page = [...this.pages.values()].filter(p => p.state === "queued")
        .sort((a,b) => this.hooks.priority(a)-this.hooks.priority(b) || a.id-b.id)[0];
      if (!page) break;
      this.controller = new AbortController(); page.state = "processing"; page.attempts++;
      this.hooks.changed();
      try {
        const result = await this.hooks.process(page, this.controller.signal);
        if (this.disposed || this.pages.get(page.key) !== page) this.hooks.release(result);
        else { page.result = result; page.state = "translated"; page.error = undefined; }
      } catch (error) {
        if (!this.disposed && this.pages.get(page.key) === page) {
          const cancelled=!this.active && error instanceof DOMException && error.name==='AbortError';
          page.state = cancelled || error instanceof SkipPage ? "skipped" : "failed";
          page.cancelled=cancelled;
          page.deferred = error instanceof WaitForViewport;
          page.error = error instanceof Error ? error.message : "Page rendering failed";
        }
      } finally { this.controller = null; this.hooks.changed(); }
    }
  }
}
