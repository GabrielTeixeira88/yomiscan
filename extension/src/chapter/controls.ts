import {ChapterTranslationSession,type ChapterSummary} from "./session";
import {coverageSummary} from './coverage';

export class ChapterControls {
  private host=document.createElement("div");
  private root=this.host.attachShadow({mode:"closed"});
  private session:ChapterTranslationSession|null=null;
  private status=document.createElement("p");
  private warning=document.createElement("p");
  private original:HTMLButtonElement;
  private english:HTMLButtonElement;
  private sessionURL=location.href;
  private stitchEnabled=false;
  constructor(selectText:()=>void) {
    this.host.dataset.yomiscan="controls";
    this.host.style.cssText="all:initial!important;position:fixed!important;top:12px!important;right:12px!important;z-index:2147483646!important;";
    const style=document.createElement("style");style.textContent=`
      :host{color-scheme:light}*{box-sizing:border-box}.chapter-panel{width:280px;max-width:calc(100vw - 24px);max-height:80vh;overflow:auto;overscroll-behavior:contain;background:#fffdf8;color:#203729;border:1px solid #b7c5ba;border-radius:12px;box-shadow:0 8px 30px #0004;padding:14px;font:14px/1.45 system-ui;text-align:left}
      header{display:flex;justify-content:space-between;align-items:center}h2{font-size:11px;text-transform:uppercase;letter-spacing:.1em;margin:14px 0 5px;color:#607669}
      button{font:inherit;cursor:pointer;border:1px solid #b7c5ba;background:#edf4ee;color:#203729;border-radius:6px;padding:7px 9px;margin:3px 3px 3px 0}button[aria-pressed=true]{background:#235d3c;color:white}button:focus-visible{outline:2px solid #287946}p{margin:8px 0;white-space:pre-wrap;overflow-wrap:anywhere}small{color:#617064}.warning{font-size:12px;color:#8a372b}summary{cursor:pointer}`;
    const panel=document.createElement("section");panel.className="chapter-panel";panel.setAttribute("aria-label","YomiScan controls");
    const header=document.createElement("header"), title=document.createElement("strong");title.textContent="YomiScan";
    const button=(label:string,action:()=>void)=>{const b=document.createElement("button");b.textContent=label;b.addEventListener("click",action);return b;};
    header.append(title,button("×",()=>{this.showHost(false);}));panel.append(header);
    const heading=(text:string)=>{const h=document.createElement("h2");h.textContent=text;panel.append(h);};
    heading("Study");panel.append(button("Select Text",selectText));
    heading("Reading");panel.append(button("Translate Chapter",()=>{void this.current().start();}),button("Stop Translation",()=>this.session?.stop()));
    const permissionHelp=document.createElement('small');permissionHelp.textContent='Translate/Retry may ask Chrome for access to this reader’s image hosts. Screenshots and analysis stay local.';
    panel.append(permissionHelp);
    const scrollLabel=document.createElement('label'),scrollOption=document.createElement('input');scrollOption.type='checkbox';
    scrollOption.addEventListener('change',()=>{this.stitchEnabled=scrollOption.checked;if(this.session)this.session.allowStitch=this.stitchEnabled;});
    scrollLabel.append(scrollOption,document.createTextNode('Allow scroll capture (moves page temporarily; Escape cancels)'));panel.append(scrollLabel);
    this.original=button("Original",()=>this.session?.setView("original"));this.english=button("English",()=>this.session?.setView("english"));
    heading("Translation View");panel.append(this.original,this.english);
    this.status.setAttribute("aria-live","polite");this.status.textContent="Ready — select a mode.";
    this.warning.className="warning";
    panel.append(this.status,this.warning,button("Retry Failed / Skipped",()=>{void this.current().start(true);}),
      button("Clear Session",()=>{this.session?.dispose();this.session=null;}));
    const help=document.createElement("small");help.textContent="Selected pages stay on this machine. CPU processing may take time.";panel.append(help);
    const details=document.createElement("details"),summary=document.createElement("summary");summary.textContent="Developer diagnostics";
    details.append(summary,button("Log discovery / states",()=>this.current().diagnostics()));panel.append(details);
    this.root.append(style,panel);this.showHost(false);document.documentElement.append(this.host);
    for(const name of ["pointerdown","pointerup","click","dblclick"])this.host.addEventListener(name,event=>event.stopPropagation());
    this.host.addEventListener("keydown",event=>{if(event.key==="Escape")this.showHost(false);event.stopPropagation();});
    window.addEventListener("pagehide",()=>{this.session?.dispose();this.session=null;});
  }
  private showHost(visible:boolean):void {this.host.style.setProperty("display",visible?"block":"none","important");}
  open():void {this.showHost(true);}
  private current():ChapterTranslationSession {
    if(this.sessionURL!==location.href || this.session?.isDisposed){this.session?.dispose();this.session=null;this.sessionURL=location.href;}
    if(!this.session)this.session=new ChapterTranslationSession(status=>this.show(status),hidden=>{this.host.style.setProperty("visibility",hidden?"hidden":"visible","important");});
    this.session.allowStitch=this.stitchEnabled;
    return this.session;
  }
  private show(status:ChapterSummary):void {
    this.original.setAttribute("aria-pressed",String(status.view==="original"));this.english.setAttribute("aria-pressed",String(status.view==="english"));
    const pending=this.session?[...this.session.queue.pages.values()].some(p=>p.state==="queued"):false;
    this.status.textContent=`${status.translated} / ${status.total} pages translated · ${status.failed} failed · ${status.skipped} skipped\n`+
      (status.processing?`Page ${status.processing} processing…`:status.active&&!pending?"Known pages finished; watching for lazy-loaded pages.":status.message);
    const errors=this.session?[...this.session.queue.pages.values()].filter(p=>p.error&&!p.cancelled).slice(0,3).map(p=>`Page ${p.id}: ${p.error}`):[];
    const results=this.session?[...this.session.queue.pages.values()].flatMap(p=>p.result?[p.result]:[]):[];
    this.warning.textContent=errors.join("\n")+'\n'+coverageSummary(results);
    if(status.message.includes("backend")||status.message.includes("server"))this.warning.textContent+="\nStart: uv run uvicorn yomiscan.api.main:app --host 127.0.0.1 --port 8765";
  }
  async prepareStudy():Promise<void> {if(this.session)await this.session.study();this.showHost(false);}
  verifyCapture(id:string):boolean{return this.session?.verifyCapture(id)??false;}
  resolveSource(id:string):string|null{return this.session?.resolveSource(id)??null;}
  resumeAfterPermission(version:number,retry:boolean):void {this.session?.resumeAfterPermission(version,retry);}
}
