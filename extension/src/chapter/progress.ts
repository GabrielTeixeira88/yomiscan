export interface JobProgress {instance:string;job_id:string;version:number;state:'processing'|'completed'|'failed'|'cancelled';current:string;
  stages:Record<string,{state:string;computed:boolean;cache_hits:number;compute_ms?:number}>;elapsed_ms?:number}
export const stageLabels:Record<string,string>={processing:'Processing locally',initializing:'Initializing required models',
  detection:'Detecting regions',ocr:'Running OCR',ordering:'Ordering regions',lexical:'Analyzing Japanese',
  translation:'Translating Japanese',render:'Rendering translation',finalizing:'Finalizing output',completed:'Completed',failed:'Failed',cancelled:'Cancelled'};
export class ProgressTracker {
  private version=0;private instance:string|null=null;
  constructor(private job:string){}
  accept(value:unknown):JobProgress|null {
    const data=value as JobProgress;
    if(!data||data.job_id!==this.job||typeof data.instance!=='string'||!/^[a-f0-9]{32}$/.test(data.instance)||
      !Number.isSafeInteger(data.version)||data.version<=this.version||!['processing','completed','failed','cancelled'].includes(data.state)||
      !Object.hasOwn(stageLabels,data.current)||!data.stages||typeof data.stages!=='object'||Array.isArray(data.stages)||
      Object.keys(data.stages).length>8||Object.entries(data.stages).some(([key,s])=>!Object.hasOwn(stageLabels,key)||
        !s||!['pending','running','cached','completed','failed','cancelled'].includes(s.state)||typeof s.computed!=='boolean'||
        !Number.isSafeInteger(s.cache_hits)||s.cache_hits<0))return null;
    if(this.instance!==null&&this.instance!==data.instance)return null;
    this.instance=data.instance;this.version=data.version;return data;
  }
}
export function progressLabel(progress:JobProgress):string {
  const stage=progress.stages[progress.current];
  const names:Record<string,string>={initializing:'Model initialization',detection:'Detection',ocr:'OCR',ordering:'Ordering',
    lexical:'Japanese analysis',translation:'Translation',render:'Rendering',finalizing:'Output finalization'};
  if(stage?.state==='cached')return (names[progress.current]??'Stage')+' — reused from cache';
  if(stage&&stage.state!=='running')return (names[progress.current]??'Stage')+' — '+stage.state;
  return stageLabels[progress.current];
}
