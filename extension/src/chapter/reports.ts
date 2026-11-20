import {packZip,type ZipEntry} from './zip';
import type {AcquisitionAttempt,AcquisitionMethod} from './acquisition';

export const MAX_SNAPSHOT=2*1024*1024;
type RecordData=Record<string,unknown>;
export interface PageSnapshot {
  schema_version:number;build:RecordData;image:{width:number;height:number;input_sha256:string;pixel_sha256?:string;canonical_pixels?:unknown};
  models:RecordData;regions:RecordData[];blocks:RecordData[];timings:RecordData;counts:RecordData;coverage?:unknown;unavailable?:string;
  cache?:unknown;
}
export interface PageReportContext {
  page_id:number;width:number;height:number;state:string;input_sha256?:string;extension_version?:string;
  job_id?:string;
  acquisition?:{method?:AcquisitionMethod;attempts:AcquisitionAttempt[]};timings:Record<string,number>;error_code?:string;
  session_cache?:{bytes:number;budget:number;evictions:number};
}
export interface ReportOptions {text:boolean;original:boolean;rendered:boolean}
export interface ReportImages {original?:Blob;rendered?:Blob}
const object=(value:unknown):RecordData=>value!==null&&typeof value==='object'&&!Array.isArray(value)?value as RecordData:{};
const finite=(value:unknown):value is number=>typeof value==='number'&&Number.isFinite(value);
const hash=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
export function parseSnapshot(value:unknown):PageSnapshot {
  const data=object(value),image=object(data.image);
  if(JSON.stringify(value)?.length>MAX_SNAPSHOT || data.schema_version!==1 ||
    !Number.isInteger(image.width)||!Number.isInteger(image.height)||Number(image.width)<=0||Number(image.height)<=0||
    Number(image.width)*Number(image.height)>12_000_000 || !hash(image.input_sha256) ||
    !Array.isArray(data.regions)||!Array.isArray(data.blocks)||data.regions.length>10000||data.blocks.length>10000)
    throw new Error('Invalid diagnostic snapshot');
  if(new TextEncoder().encode(JSON.stringify(value)).length>MAX_SNAPSHOT)throw new Error('Diagnostic snapshot exceeds 2 MiB');
  return {...data,build:object(data.build),models:object(data.models),counts:object(data.counts),
    timings:object(data.timings),image,regions:data.regions.map(object),blocks:data.blocks.map(object)} as PageSnapshot;
}
function label(value:unknown):string|null {
  return typeof value==='string' && value.length<=180 && /^[a-z0-9_. /-]+$/i.test(value) &&
    !value.startsWith('/')&&!value.includes('..') ? value:null;
}
function pick(value:unknown,keys:string[]):RecordData {
  const input=object(value),result:RecordData={};
  for(const key of keys) {
    const v=input[key];
    if(v===null||typeof v==='boolean'||finite(v))result[key]=v;
    else if(typeof v==='string')result[key]=label(v);
  }
  return result;
}
const bbox=(value:unknown)=>Array.isArray(value)&&value.length===4&&value.every(finite)?value:
  pick(value,['left','top','right','bottom']);
const ids=(value:unknown)=>Array.isArray(value)?value.filter(v=>Number.isInteger(v)&&v>=0):[];
function models(value:unknown):RecordData {
  const input=object(value),output:RecordData={};
  for(const key of ['translation','detection','ocr','settings'])
    output[key]=pick(input[key],['engine','model','revision','model_revision','expected_revision','base_model','base_revision',
      'device','analysis_device','target_language','threshold','bubble_threshold','free_threshold','artifact','source_revision',
      'preprocessing','decoding','threads','max_tokens','kv_cache']);
  for(const key of ['translation','settings'])Object.assign(object(output[key]),
    pick(input[key],['batch_size','num_beams','context_tokens','temperature','seed','prompt_version','padding','minimum_side',
      'minimum_font_size','maximum_font_size','preferred_font_size','font_margin']));
  return output;
}
function timings(value:unknown):RecordData {
  const output:RecordData={};
  for(const [key,v] of Object.entries(object(value))) {
    if(!/^[a-z_]+(?:ms)?$/.test(key))continue;
    if(finite(v)&&v>=0)output[key]=v;
    else if(v!==null&&typeof v==='object'&&!Array.isArray(v))output[key]=timings(v);
  }
  return output;
}
function text(value:unknown):string|null {
  if(typeof value!=='string')return null;
  return value.replace(/https?:\/\/[^\s<>"']+/gi,'[URL removed]')
    .replace(/\b(?:authorization|cookie|set-cookie|referrer|referer)\s*:\s*[^\r\n]+/gi,'[header removed]')
    .replace(/\b(?:authorization|cookie|password|token|api[_-]?key)\s*[:=]\s*[^\s,;]+(?:\s+[^\s,;]+)?/gi,'[credential removed]')
    .replace(/\b[A-Z]:[\\/][^\r\n<>"']+/gi,'[local path removed]')
    .replace(/\\\\[^\s\\]+\\[^\r\n<>"']+/g,'[local path removed]')
    .replace(/(?:^|\s)\/(?:Users|home|tmp|var|mnt|etc|root|opt|workspace|Volumes)\/[^\s]+/g,' [local path removed]');
}
export async function imageHash(blob:Blob):Promise<string> {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer()))].map(n=>n.toString(16).padStart(2,'0')).join('');
}
export async function createPageReport(context:PageReportContext,snapshot:PageSnapshot|undefined,options:ReportOptions,
  images:ReportImages={}):Promise<Blob> {
  if(snapshot && (snapshot.image.input_sha256!==context.input_sha256 ||
    snapshot.image.width!==context.width||snapshot.image.height!==context.height))throw new Error('Report page identity does not match');
  const missing:string[]=[];
  if(!snapshot)missing.push('Backend snapshot unavailable; no analysis was rerun.');
  if(snapshot?.unavailable)missing.push('Backend diagnostic size limit reached.');
  const acquisition=context.acquisition;
  const manifest={
    schema_version:1,
    build:pick(snapshot?.build,['version','revision']),extension_version:label(context.extension_version),
    page:{id:context.page_id,job_id:label(context.job_id),state:label(context.state),width:context.width,height:context.height,
      input_sha256:hash(context.input_sha256)?context.input_sha256:null,
      pixel_sha256:hash(snapshot?.image.pixel_sha256)?snapshot.image.pixel_sha256:null},
    models:models(snapshot?.models),counts:pick(snapshot?.counts,['rendered','preserved','undetected']),
    canonical_pixels:pick(snapshot?.image.canonical_pixels,['sha256','normalization','width','height','mode']),
    cache:{...pick(snapshot?.cache,['schema','persistent_enabled','memory_bytes','memory_limit','disk_bytes','disk_limit',
      'hits','misses','evictions','corruptions','refresh','error_code']),
      stages:(Array.isArray(object(snapshot?.cache).stages)?object(snapshot?.cache).stages as unknown[]:[]).map(
        stage=>pick(stage,['stage','key','source','restored','lookup_ms','compute_ms'])),
      session:pick(context.session_cache,['bytes','budget','evictions'])},
    acquisition:{method:label(acquisition?.method),resolution:'acquired_pixels',
      attempts:(acquisition?.attempts??[]).map(a=>({method:label(a.method),success:a.success,
        outcome:a.success?'success':'failed',code:label(a.code)}))},
    error_code:label(context.error_code),inclusions:options,missing,
    privacy:'Saved locally by explicit action. No source URL, credentials, machine paths or raw exceptions included.',
  };
  const regions={regions:(snapshot?.regions??[]).map(r=>({...pick(r,['id','confidence','class','filtered']),bbox:bbox(r.bbox),block_ids:ids(r.block_ids)})),
    blocks:(snapshot?.blocks??[]).map(b=>({
      ...pick(b,['id','reading_order','orientation','detection_confidence']),region_ids:ids(b.region_ids),bbox:bbox(b.bbox),
      ocr:pick(b.ocr,['status','engine','model','revision','confidence','confidence_method','processing_ms',
        'recognition_status','termination','tokens','uncertainty','preprocessing','decoding','kv_cache']),
      translation:pick(b.translation,['status','failure_stage','rejected','complete','engine','model','revision','expected_revision','device']),
      render:{...pick(b.render,['status','reason_code','reason','mask','mask_method','inpainting','layout','typesetting','font_size','category']),
        layout_bbox:bbox(object(b.render).layout_bbox)},
    }))};
  const encode=(value:unknown)=>new TextEncoder().encode(JSON.stringify(value,null,2));
  const entries:ZipEntry[]=[{name:'manifest.json',data:encode(manifest)},{name:'regions.json',data:encode(regions)},
    {name:'timings.json',data:encode({browser:timings(context.timings),backend:timings(snapshot?.timings)})}];
  if(options.text) {
    entries.push({name:'optional/translation-debug.json',data:encode((snapshot?.blocks??[]).map(b=>({
      id:b.id,original:text(object(b.text).original),translation_input:text(object(b.text).translation_input),
      translation:text(object(b.text).translation),
    })))});
    if(!snapshot)missing.push('OCR/translation text unavailable.');
  }
  for(const key of ['original','rendered'] as const)if(options[key]) {
    const blob=images[key];
    if(!blob){missing.push(key+' image unavailable in this session.');continue;}
    const ext=blob.type==='image/png'?'png':blob.type==='image/jpeg'?'jpg':blob.type==='image/webp'?'webp':null;
    if(!ext)throw new Error('Unsupported report image');
    // Original bytes are decoded and re-encoded, dropping EXIF/ancillary metadata.
    const bitmap=await createImageBitmap(blob);
    try {
      const canvas=new OffscreenCanvas(bitmap.width,bitmap.height),ctx=canvas.getContext('2d');
      if(!ctx || bitmap.width*bitmap.height>12_000_000)throw new Error('Invalid report image dimensions');
      ctx.drawImage(bitmap,0,0);
      const png=await canvas.convertToBlob({type:'image/png'});
      entries.push({name:'optional/'+key+'.png',data:new Uint8Array(await png.arrayBuffer())});
      canvas.width=canvas.height=0;
    } finally {bitmap.close();}
  }
  entries[0].data=encode(manifest); // Include missing optional artifacts discovered above.
  return packZip(entries);
}
