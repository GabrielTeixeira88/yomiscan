import {parseAnalysis,type Analysis} from './api';

export const HISTORY_KEY='yomiscanStudyHistoryV1',HISTORY_COUNT=100,HISTORY_BYTES=2*1024*1024,ENTRY_BYTES=128*1024;
export interface HistoryEntry {id:string;created_at:string;analysis:Analysis}
export interface HistoryState {schema:1;enabled:boolean;entries:HistoryEntry[]}
export interface HistoryStorage {get(key:string):Promise<Record<string,unknown>>;set(items:Record<string,unknown>):Promise<void>}
const bytes=(data:unknown)=>new TextEncoder().encode(JSON.stringify(data)).length;

/** Explicitly selected text/analysis only; ignore transport fields, URLs and pixels. */
export function historyAnalysis(value:unknown):Analysis {
  const data=parseAnalysis(value);
  const result:Analysis={original_text:data.original_text,translation:data.translation,
    target_language:data.target_language??'en',dictionary_language:'en',processing:{ocr_ms:data.processing.ocr_ms,
      translation_ms:data.processing.translation_ms,analysis_ms:data.processing.analysis_ms,total_ms:data.processing.total_ms},
    tokens:data.tokens.map(t=>({surface:t.surface,reading:t.reading,lemma:t.lemma,dictionary_form:t.dictionary_form,
      part_of_speech:t.part_of_speech,conjugation_type:t.conjugation_type,conjugation_form:t.conjugation_form,
      meanings:t.meanings.map(m=>({entry_id:m.entry_id,glosses:[...m.glosses],parts_of_speech:[...m.parts_of_speech],
        spellings:[...m.spellings],readings:[...m.readings],notes:[...m.notes],labels:[...m.labels]}))}))};
  if(data.units)result.units=data.units.map(u=>({surface:u.surface,dictionary_form:u.dictionary_form,start_token:u.start_token,
    end_token:u.end_token,meanings:u.meanings.map(m=>({entry_id:m.entry_id,glosses:[...m.glosses],parts_of_speech:[...m.parts_of_speech],
      spellings:[...m.spellings],readings:[...m.readings],notes:[...m.notes],labels:[...m.labels]}))}));
  if(data.provenance){const allowed=['engine','model','revision','expected_revision','requested_target','target_language','grammar_contract','translation_mode','context_policy','glossary_application','analysis_origin'];
    result.provenance=Object.fromEntries(Object.entries(data.provenance).filter(([k,v])=>allowed.includes(k)&&typeof v==='string'&&v.length<=160&&/^[\w.-]+(?:\/[\w.-]+)?$/.test(v)));
  }
  if(bytes(result)>ENTRY_BYTES)throw new Error('Study entry exceeds 128 KiB; nothing saved.');
  return result;
}

export class StudyHistory {
  private tail:Promise<unknown>=Promise.resolve();
  constructor(private storage:HistoryStorage){}
  private async read():Promise<HistoryState> {
    const data=(await this.storage.get(HISTORY_KEY))[HISTORY_KEY];
    if(data===undefined)return {schema:1,enabled:false,entries:[]};
    const state=data as HistoryState;
    if(!state||state.schema!==1||typeof state.enabled!=='boolean'||!Array.isArray(state.entries)||state.entries.length>HISTORY_COUNT||bytes(state)>HISTORY_BYTES)
      throw new Error('Local history is invalid. Export/recover it from extension storage or explicitly Clear History.');
    return {schema:1,enabled:state.enabled,entries:state.entries.map(entry=>{
      if(!entry||!/^[a-f0-9-]{36}$/.test(entry.id)||typeof entry.created_at!=='string'||!Number.isFinite(Date.parse(entry.created_at)))throw new Error('Invalid stored study entry.');
      return {id:entry.id,created_at:entry.created_at,analysis:historyAnalysis(entry.analysis)};
    })};
  }
  request(operation:string,payload:Record<string,unknown>={}):Promise<HistoryState> {
    const task=this.tail.then(async()=>{
      if(operation==='clear'){
        const raw=(await this.storage.get(HISTORY_KEY))[HISTORY_KEY] as Partial<HistoryState>|undefined;
        const cleared:HistoryState={schema:1,enabled:raw?.enabled===true,entries:[]};
        await this.storage.set({[HISTORY_KEY]:cleared});return cleared;
      }
      const state=await this.read();
      if(operation==='state'||operation==='export')return state;
      if(operation==='enabled'){
        if(typeof payload.enabled!=='boolean')throw new Error('Choose whether to enable local Study history.');
        state.enabled=payload.enabled;
      }else if(operation==='save'){
        if(!state.enabled)throw new Error('History is off. Enable it in Study history, then explicitly Save to History.');
        const entry={id:crypto.randomUUID(),created_at:new Date().toISOString(),analysis:historyAnalysis(payload.analysis)};
        state.entries.unshift(entry);state.entries=state.entries.slice(0,HISTORY_COUNT);
        while(bytes(state)>HISTORY_BYTES&&state.entries.length>1)state.entries.pop();
        if(bytes(state)>HISTORY_BYTES)throw new Error('Local history quota exceeded; nothing saved.');
      }else if(operation==='delete'){
        if(typeof payload.id!=='string')throw new Error('Choose a study entry to delete.');
        state.entries=state.entries.filter(e=>e.id!==payload.id);
      }else throw new Error('Unknown history operation');
      await this.storage.set({[HISTORY_KEY]:state});return state;
    });
    this.tail=task.catch(()=>{});return task;
  }
}
