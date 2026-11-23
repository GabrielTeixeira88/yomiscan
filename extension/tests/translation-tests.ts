import test from 'node:test';
import assert from 'node:assert/strict';
import {defaultTranslationOptions,validateTranslationOptions,validateProfile,type TranslationProfile} from '../src/chapter/translation-options';
import {translationRequest} from '../src/chapter/translation-client';

const profile=():TranslationProfile=>({engine:{},capabilities:{targets:['en'],glossary_hints:false,structured:false,
  bounded_context:false,experimental_targets:[]},default_target:'en',series:[{id:'global',label:'Global'}],scope:'global',
  target_language:'en',entries:[],glossary_version:'a'.repeat(64),dictionary_language:'en',configuration_id:'b'.repeat(64)});

test('reader defaults preserve English; strict options reject unsupported shapes and unstructured context',()=>{
  assert.deepEqual(validateTranslationOptions(defaultTranslationOptions()),defaultTranslationOptions());
  for(const change of [{target_language:'fr'},{mode:'page'},{context:'page'},{series_id:'https://private/series'},
    {glossary_version:'stale'},{path:'private'},{glossary_enabled:'yes'}])
    assert.throws(()=>validateTranslationOptions({...defaultTranslationOptions(),...change}));
  assert.equal(validateTranslationOptions({...defaultTranslationOptions(),mode:'structured-line',context:'neighbor'}).context,'neighbor');
});
test('profile declares real target capabilities and keeps dictionary language separate',()=>{
  assert.equal(validateProfile(profile()).default_target,'en');
  assert.throws(()=>validateProfile({...profile(),default_target:'es'}));
  assert.throws(()=>validateProfile({...profile(),dictionary_language:'pt-BR'}));
  assert.throws(()=>validateProfile({...profile(),scope:'unknown'}));
});
test('terminology client uses fixed protected localhost endpoints and bounded responses',async()=>{
  const native=globalThis.fetch,calls:{url:string;options:RequestInit}[]=[];
  try{
    globalThis.fetch=async(input,options)=>{calls.push({url:String(input),options:options!});return Response.json(profile());};
    await translationRequest('profile',{scope:'global',target:'en'});
    assert.equal(calls[0].url,'http://127.0.0.1:47615/api/v1/translation-profile?scope=global&target=en');
    assert.equal(calls[0].options.method,'GET');assert.equal(calls[0].options.credentials,'omit');
    assert.equal((calls[0].options.headers as Record<string,string>)['X-YomiScan-Client'],'study-extension-v1');
    await translationRequest('save-term',{scope:'global',source:'猫',preferred:'cat'});
    assert.equal(calls[1].options.method,'POST');
    await assert.rejects(translationRequest('save-term',{source:'x'.repeat(1801)}),/Invalid/);
    globalThis.fetch=async()=>new Response('',{status:429});
    await assert.rejects(translationRequest('profile',{}),/Stop translation/);
    globalThis.fetch=async()=>new Response('',{headers:{'Content-Length':String(3*1024*1024)}});
    await assert.rejects(translationRequest('profile',{}),/size limit/);
  }finally{globalThis.fetch=native;}
});
