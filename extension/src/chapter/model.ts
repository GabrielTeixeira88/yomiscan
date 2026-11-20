export type PageState = "queued" | "processing" | "translated" | "failed" | "skipped";
export type ViewMode = "original" | "english";
export interface PageRecord<T, R> {
  id: number; key: object; identity: string; source: T; state: PageState;
  result?: R; error?: string; attempts: number; cancelled?: boolean; deferred?: boolean;
  refreshing?:boolean;
}
export class SkipPage extends Error { readonly retryWhenVisible:boolean=false; }
export class WaitForViewport extends SkipPage { override readonly retryWhenVisible:boolean=true; }
/** A new viewport cannot fix permissions, authentication, or unsupported input. */
export class ManualAcquisitionError extends SkipPage {}

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
  private current:PageRecord<T,R>|null=null;
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
      page.state = page.result ? "translated" : "skipped"; page.cancelled = !page.result;
      page.refreshing=false;page.error = "Stopped before processing";
    }
    if(this.current?.refreshing)this.controller?.abort();
    // Already submitted inference may finish; its result is retained for toggling.
    this.hooks.changed();
  }
  retry(): void {
    for (const page of this.pages.values()) if (page.state === "failed" || page.state === "skipped") {
      page.state = "queued"; page.error = undefined; page.cancelled = false;
    }
    this.start();
  }
  /** Explicit refresh bypasses this result without clearing neighbors or the visible image. */
  refresh(key:object):boolean {
    const page=this.pages.get(key);
    if(this.disposed || !page?.result || page.state==="queued" || page.state==="processing")return false;
    page.refreshing=true;page.state="queued";page.error=undefined;page.cancelled=false;page.deferred=false;
    this.active=true;this.hooks.changed();this.schedule();return true;
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
      const controller=this.controller = new AbortController();this.current=page;
      page.state = "processing"; page.attempts++;
      this.hooks.changed();
      try {
        const result = await this.hooks.process(page, controller.signal);
        if (this.disposed || this.pages.get(page.key) !== page || controller.signal.aborted) {
          this.hooks.release(result);
          if(!this.disposed && this.pages.get(page.key)===page && page.result) {
            page.state="translated";page.error="Refresh cancelled; previous translation retained.";
          }
        } else {
          if(page.result)this.hooks.release(page.result);
          page.result = result; page.state = "translated"; page.error = undefined;
        }
      } catch (error) {
        if (!this.disposed && this.pages.get(page.key) === page) {
          const cancelled=controller.signal.aborted || (!this.active && error instanceof DOMException && error.name==='AbortError');
          page.state = page.result ? "translated" : cancelled || error instanceof SkipPage ? "skipped" : "failed";
          page.cancelled=cancelled && !page.result;
          page.deferred = !page.result && error instanceof SkipPage && error.retryWhenVisible;
          page.error = page.result ? (cancelled?"Refresh cancelled":"Refresh failed")+"; previous translation retained." :
            error instanceof Error ? error.message : "Page rendering failed";
        }
      } finally { page.refreshing=false;this.controller = null;this.current=null;this.hooks.changed(); }
    }
  }
}
