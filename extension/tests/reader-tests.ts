import test from 'node:test';
import assert from 'node:assert/strict';
import {fontScale,retainsRenderedBlocks} from '../src/chapter/font-settings';
import {displayedRegion} from '../src/chapter/region-geometry';
import {inspectionRegions} from '../src/chapter/region-inspector';
import {ProgressTracker,progressLabel} from '../src/chapter/progress';
import {parseSnapshot} from '../src/chapter/reports';
import {validateReadiness} from '../src/chapter/setup-controls';

const analysis=()=>({original_text:'猫です',translation:'It is a cat.',target_language:'en',processing:{ocr_ms:1,translation_ms:1,analysis_ms:1,total_ms:3},tokens:[]});
test('font bounds and mapped regions reject unsafe dimensions',()=>{
  for(const value of [NaN,Infinity,0,.74,1.51,'1'])assert.throws(()=>fontScale(value));
  assert.equal(fontScale(1),1);assert.equal(fontScale(.75),.75);assert.equal(fontScale(1.5),1.5);
  const box={x:50,y:100,width:100,height:80},pixels={width:400,height:800};
  assert.deepEqual(displayedRegion(box,pixels,{x:10,y:-40,width:200,height:400}),{x:35,y:10,width:50,height:40});
  assert.equal(displayedRegion(box,pixels,{x:0,y:0,width:100,height:100}),null);
  assert.equal(displayedRegion({...box,x:900},pixels,{x:0,y:0,width:400,height:800}),null);
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
