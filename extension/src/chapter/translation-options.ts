export type TargetLanguage='en'|'pt-BR'|'es';
export interface ReaderTranslationOptions {
  target_language:TargetLanguage;series_id:string|null;glossary_enabled:boolean;glossary_version:string|null;
  mode:'sentences'|'structured-line'|'structured-page'|'structured-panel';ordering:'bands'|'panels';context:'none'|'neighbor'|'panel'|'page';
}
export const defaultTranslationOptions=():ReaderTranslationOptions=>({target_language:'en',series_id:null,
  glossary_enabled:false,glossary_version:null,mode:'sentences',ordering:'bands',context:'none'});
export const targetLabel=(target:TargetLanguage):string=>target==='en'?'English':target==='pt-BR'?'Português (experimental)':'Español (experimental)';
export function validateTranslationOptions(value:unknown):ReaderTranslationOptions {
  if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('Invalid translation options');
  const data=value as Record<string,unknown>,known=Object.keys(defaultTranslationOptions());
  if(Object.keys(data).some(k=>!known.includes(k))||!['en','pt-BR','es'].includes(String(data.target_language))||
    typeof data.glossary_enabled!=='boolean'||!['sentences','structured-line','structured-page','structured-panel'].includes(String(data.mode))||
    !['bands','panels'].includes(String(data.ordering))||!['none','neighbor','panel','page'].includes(String(data.context))||
    (data.series_id!==null&&data.series_id!=='global'&&!(typeof data.series_id==='string'&&/^[a-f0-9-]{36}$/.test(data.series_id)))||
    (data.glossary_version!==null&&!(typeof data.glossary_version==='string'&&/^[a-f0-9]{64}$/.test(data.glossary_version)))||
    (data.context!=='none'&&data.mode==='sentences'))throw new Error('Invalid translation options');
  return data as unknown as ReaderTranslationOptions;
}

export interface GlossaryTerm {id:string;scope:string;target_language:TargetLanguage;source:string;preferred:string}
export interface TranslationProfile {
  engine:Record<string,unknown>;capabilities:{targets:TargetLanguage[];glossary_hints:boolean;structured:boolean;bounded_context:boolean;experimental_targets:TargetLanguage[]};
  default_target:TargetLanguage;series:{id:string;label:string}[];scope:string;target_language:TargetLanguage;
  entries:GlossaryTerm[];glossary_version:string;dictionary_language:'en';configuration_id:string;
}
export function validateProfile(value:unknown):TranslationProfile {
  const data=value as TranslationProfile;
  if(!data||!Array.isArray(data.series)||data.series.length>101||!data.series.every(s=>typeof s.id==='string'&&typeof s.label==='string'&&s.label.length<=100)||
    !Array.isArray(data.entries)||data.entries.length>1000||!data.entries.every(e=>typeof e.id==='string'&&typeof e.source==='string'&&typeof e.preferred==='string')||
    !data.capabilities||!Array.isArray(data.capabilities.targets)||!data.capabilities.targets.length||
    !data.capabilities.targets.every(t=>['en','pt-BR','es'].includes(t))||typeof data.capabilities.glossary_hints!=='boolean'||
    typeof data.capabilities.structured!=='boolean'||typeof data.capabilities.bounded_context!=='boolean'||
    !data.capabilities.targets.includes(data.default_target)||!data.capabilities.targets.includes(data.target_language)||
    !Array.isArray(data.capabilities.experimental_targets)||!data.capabilities.experimental_targets.every(t=>data.capabilities.targets.includes(t))||
    !data.series.some(s=>s.id===data.scope)||typeof data.configuration_id!=='string'||
    !/^[a-f0-9]{64}$/.test(data.glossary_version)||data.dictionary_language!=='en')throw new Error('Invalid local translation profile');
  return data;
}
