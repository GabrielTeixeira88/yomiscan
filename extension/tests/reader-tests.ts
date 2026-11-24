import test from 'node:test';
import assert from 'node:assert/strict';
import {StudyHistory,HISTORY_KEY,HISTORY_COUNT,historyAnalysis,type HistoryStorage} from '../src/history';
import {fontScale,retainsRenderedBlocks} from '../src/chapter/font-settings';
import {displayedRegion} from '../src/chapter/region-geometry';
import {inspectionRegions} from '../src/chapter/region-inspector';
import {ProgressTracker,progressLabel} from '../src/chapter/progress';
import {parseSnapshot} from '../src/chapter/reports';
import {validateReadiness} from '../src/chapter/setup-controls';

const analysis=()=>({original_text:'猫です',translation:'It is a cat.',target_language:'en',processing:{ocr_ms:1,translation_ms:1,analysis_ms:1,total_ms:3},tokens:[]});
function storage(){let data:Record<string,unknown>={},writes=0;return {get:async()=>structuredClone(data),
  set:async(items:Record<string,unknown>)=>{data={...data,...structuredClone(items)};writes++;},writes:()=>writes};}
test('font bounds and mapped regions reject unsafe dimensions',()=>{
  for(const value of [NaN,Infinity,0,.74,1.51,'1'])assert.throws(()=>fontScale(value));
  assert.equal(fontScale(1),1);assert.equal(fontScale(.75),.75);assert.equal(fontScale(1.5),1.5);
  const box={x:50,y:100,width:100,height:80},pixels={width:400,height:800};
  assert.deepEqual(displayedRegion(box,pixels,{x:10,y:-40,width:200,height:400}),{x:35,y:10,width:50,height:40});
  assert.equal(displayedRegion(box,pixels,{x:0,y:0,width:100,height:100}),null);
  assert.equal(displayedRegion({...box,x:900},pixels,{x:0,y:0,width:400,height:800}),null);
});
test('study history remains off and never writes before explicit opt-in and Save',async()=>{
  const disk=storage(),history=new StudyHistory(disk);
  assert.equal((await history.request('state')).enabled,false);assert.equal(disk.writes(),0);
  await assert.rejects(history.request('save',{analysis:analysis()}),/off/);assert.equal(disk.writes(),0);
  await history.request('enabled',{enabled:true});await history.request('save',{analysis:{...analysis(),source_url:'https://private',image:'data:private'}});
  const restarted=new StudyHistory(disk),state=await restarted.request('state');assert.equal(state.entries.length,1);
  assert.ok(!JSON.stringify(state).includes('private'));assert.deepEqual(state.entries[0].analysis,{...analysis(),dictionary_language:'en'});
});
test('history retention, quota, export, deletion and cache/glossary independence',async()=>{
  const disk=storage(),history=new StudyHistory(disk);
  await history.request('enabled',{enabled:true});
  for(let i=0;i<HISTORY_COUNT+1;i++)await history.request('save',{analysis:{...analysis(),original_text:'猫'+i}});
  let state=await history.request('export');assert.equal(state.entries.length,HISTORY_COUNT);
  assert.equal(state.entries.at(-1)?.analysis.original_text,'猫1');
  await disk.set({unrelatedGlossary:'preserve',processingCache:'preserve'});
  await history.request('enabled',{enabled:false});await assert.rejects(history.request('save',{analysis:analysis()}),/off/);
  state=await history.request('delete',{id:state.entries[0].id});assert.equal(state.entries.length,HISTORY_COUNT-1);
  assert.equal((await history.request('clear')).entries.length,0);
  assert.equal((await disk.get()).unrelatedGlossary,'preserve');assert.equal((await disk.get()).processingCache,'preserve');
  assert.throws(()=>historyAnalysis({...analysis(),original_text:'猫'.repeat(60_000)}),/128 KiB/);
  assert.equal((await history.request('state')).enabled,false);
});
test('history stores only whitelisted processing and provenance fields',()=>{
  const saved=historyAnalysis({...analysis(),processing:{...analysis().processing,path:'C:/private'},
    provenance:{engine:'current',artifact:'C:/private',model:'/home/private/file'},source_url:'https://private'});
  assert.ok(!JSON.stringify(saved).includes('private'));assert.deepEqual(saved.provenance,{engine:'current'});
});
test('history keeps expression units and drops their unknown fields',()=>{
  const meaning={entry_id:7,glosses:['maybe'],parts_of_speech:['expressions'],spellings:[],readings:[],notes:[],labels:[]};
  const token={surface:'猫',reading:'ねこ',lemma:'猫',dictionary_form:'猫',part_of_speech:'名詞',conjugation_type:null,conjugation_form:null,meanings:[]};
  const base={...analysis(),tokens:[token]},unit={surface:'猫',dictionary_form:'猫',start_token:0,end_token:1,meanings:[meaning]};
  const saved=historyAnalysis({...base,units:[{...unit,private:'C:/x'}]});
  assert.deepEqual(saved.units,[unit]);
  assert.equal(historyAnalysis(base).units,undefined);
});
test('history byte quota evicts oldest sentences before the count limit',async()=>{
  const disk=storage(),history=new StudyHistory(disk);
  await history.request('enabled',{enabled:true});
  for(let i=0;i<30;i++)await history.request('save',{analysis:{...analysis(),original_text:String(i)+'猫'.repeat(30_000)}});
  const state=await history.request('export');
  assert.ok(state.entries.length<30&&state.entries.length>0);
  assert.ok(new TextEncoder().encode(JSON.stringify(state)).length<=2*1024*1024);
  assert.ok(state.entries[0].analysis.original_text.startsWith('29'));
});
test('job tracker rejects other tabs, stale versions, backend restarts and unsupported shapes',()=>{
  const tracker=new ProgressTracker('job-a'),base={job_id:'job-a',instance:'a'.repeat(32),version:1,state:'processing',current:'ocr',
    stages:{ocr:{state:'cached',computed:false,cache_hits:2}}};
  const first=tracker.accept(base);assert.ok(first);assert.match(progressLabel(first),/cache/);assert.doesNotMatch(progressLabel(first),/Running/);
  assert.equal(tracker.accept(base),null);assert.equal(tracker.accept({...base,version:2,job_id:'job-b'}),null);
  assert.equal(tracker.accept({...base,version:2,instance:'b'.repeat(32)}),null);
  assert.equal(tracker.accept({...base,version:2,current:'Japanese private'}),null);
  assert.ok(tracker.accept({...base,version:2,state:'cancelled',current:'cancelled'}));
});
test('region inspection reuses only an analysis bound to the selected block text',()=>{
  const snapshot=parseSnapshot({schema_version:1,build:{},models:{},timings:{},counts:{},regions:[],
    image:{width:400,height:800,input_sha256:'a'.repeat(64)},blocks:[{id:1,bbox:{left:10,top:20,right:90,bottom:100},
      render:{reason_code:'overflow'},ocr:{confidence:.7},detection_confidence:.91,text:{original:'猫です',translation:'It is a cat.',study:analysis()}}]});
  assert.equal(inspectionRegions(snapshot)[0].study?.original_text,'猫です');
  assert.match(inspectionRegions(snapshot)[0].reason,/fit/);
  assert.equal(inspectionRegions(snapshot)[0].detectionConfidence,.91);
  (snapshot.blocks[0].text as Record<string,unknown>).study={...analysis(),original_text:'別のページ'};
  assert.equal(inspectionRegions(snapshot)[0].study,null);
});
test('font replacement retains every formerly rendered block, including unchanged total counts',()=>{
  const snapshot=(ids:number[])=>parseSnapshot({schema_version:1,image:{width:400,height:800,input_sha256:'a'.repeat(64)},regions:[],
    blocks:ids.map(id=>({id,render:{status:'rendered'}}))});
  const previous={rendered:2,snapshot:snapshot([1,2])};
  assert.ok(retainsRenderedBlocks(previous,{rendered:3,snapshot:snapshot([1,2,3])}));
  assert.ok(!retainsRenderedBlocks(previous,{rendered:1,snapshot:snapshot([1])}));
  assert.ok(!retainsRenderedBlocks(previous,{rendered:2,snapshot:snapshot([1,3])}));
  assert.ok(!retainsRenderedBlocks(previous,{rendered:2}));
});
test('outdated readiness responses fail with update guidance rather than crashing UI rendering',()=>{
  assert.throws(()=>validateReadiness({schema:1,version:'old',initialization:'ready',busy:false,models:[]}),/Update the backend/);
});
