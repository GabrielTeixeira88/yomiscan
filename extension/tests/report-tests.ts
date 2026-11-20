import test from 'node:test';
import assert from 'node:assert/strict';
import {packZip,unpackZip} from '../src/chapter/zip';
import {createPageReport,parseSnapshot,type PageReportContext} from '../src/chapter/reports';
import {readRenderResponse} from '../src/chapter/render-response';

const context:PageReportContext={page_id:2,width:800,height:1100,state:'translated',input_sha256:'a'.repeat(64),
  acquisition:{method:'canvas',attempts:[{method:'direct-extension-fetch',success:false,reason:'https://secret.example/?token=secret'},
    {method:'canvas',success:true}]},timings:{acquisition_ms:2,total_ms:12}};
const snapshot=()=>({schema_version:1,build:{version:'0.1.0',revision:null},
  image:{width:800,height:1100,input_sha256:'a'.repeat(64)},models:{translation:{engine:'current',model:'Helsinki-NLP/opus-mt-ja-en'}},
  regions:[{id:7,bbox:[1,2,3,4],confidence:.9,block_ids:[1]}],
  blocks:[{id:1,region_ids:[7],bbox:{left:1,top:2,right:3,bottom:4},reading_order:1,
    ocr:{status:'success',confidence:null},translation:{status:'success'},
    render:{status:'skipped',reason_code:'overflow'},text:{original:'秘密の猫',translation:'Secret cat',translation_input:'秘密の猫'}}],
  timings:{analysis:{ocr_ms:3}},counts:{rendered:0,preserved:1,undetected:null}});

test('ZIP round trip checks CRC, bounds and fixed safe paths',async()=>{
  const encoded=packZip([{name:'manifest.json',data:new TextEncoder().encode('{"ok":true}')}]);
  const entries=await unpackZip(encoded);
  assert.equal(new TextDecoder().decode(entries.get('manifest.json')),'{"ok":true}');
  const damaged=new Uint8Array(await encoded.arrayBuffer());damaged[43]^=1;
  await assert.rejects(()=>unpackZip(new Blob([damaged])),/ZIP/);
  assert.throws(()=>packZip([{name:'../escape',data:new Uint8Array()}]),/path/);
  assert.throws(()=>packZip([{name:'large',data:new Uint8Array(100)}],90),/limit/);
});

test('metadata-only report excludes text, raw errors, paths, URLs and unknown fields',async()=>{
  const source={...snapshot(),credentials:'never-share',local_path:'C:/private',url:'https://secret/?token=secret'};
  const zip=await createPageReport(context,parseSnapshot(source),{text:false,original:false,rendered:false});
  const entries=await unpackZip(zip);
  assert.deepEqual([...entries.keys()],['manifest.json','regions.json','timings.json']);
  const output=[...entries.values()].map(x=>new TextDecoder().decode(x)).join('');
  for(const forbidden of ['秘密の猫','Secret cat','never-share','C:/private','https://secret','token=secret'])assert.ok(!output.includes(forbidden));
  const regions=JSON.parse(new TextDecoder().decode(entries.get('regions.json')));
  assert.equal(regions.blocks[0].render.reason_code,'overflow');
  assert.equal(regions.blocks[0].ocr.confidence,null);
});

test('text requires explicit inclusion, is redacted, and cannot attach to a different page',async()=>{
  const data=snapshot();data.blocks[0].text.translation='See https://private.example/?token=secret and C:\\Users\\private';
  const parsed=parseSnapshot(data);
  const zip=await createPageReport(context,parsed,{text:true,original:false,rendered:false});
  const entries=await unpackZip(zip),output=new TextDecoder().decode(entries.get('optional/translation-debug.json'));
  assert.ok(output.includes('秘密の猫'));assert.ok(!output.includes('private.example'));assert.ok(!output.includes('Users'));
  data.blocks[0].text.translation='Cookie: session=private-cookie; auth=private-auth\nAuthorization: Bearer private-bearer\nReferrer: private-referrer\n\\\\private-host\\share\\file\n/etc/private-file';
  const redacted=await unpackZip(await createPageReport(context,parseSnapshot(data),{text:true,original:false,rendered:false}));
  assert.ok(!new TextDecoder().decode(redacted.get('optional/translation-debug.json')).includes('private-'));
  await assert.rejects(()=>createPageReport({...context,input_sha256:'b'.repeat(64)},parsed,
    {text:false,original:false,rendered:false}),/identity/);
  await assert.rejects(()=>createPageReport({...context,width:801},parsed,
    {text:false,original:false,rendered:false}),/identity/);
});

test('failed pages and missing snapshots export explicit availability instead of rerunning anything',async()=>{
  const zip=await createPageReport({...context,state:'failed',error_code:'acquisition_failed'},undefined,
    {text:false,original:false,rendered:false});
  const entries=await unpackZip(zip),manifest=JSON.parse(new TextDecoder().decode(entries.get('manifest.json')));
  assert.equal(manifest.error_code,'acquisition_failed');assert.match(manifest.missing[0],/no analysis was rerun/);
  assert.throws(()=>parseSnapshot({...snapshot(),unknown:'x'.repeat(2*1024*1024)}),/snapshot/);
});

test('render transport checks ZIP identity and preserves compatibility with a legacy PNG backend',async()=>{
  const encode=(x:unknown)=>new TextEncoder().encode(JSON.stringify(x));
  const bundle=()=>packZip([{name:'rendered.png',data:new Uint8Array([1,2,3])},
    {name:'snapshot.json',data:encode(snapshot())}]);
  const page=await readRenderResponse(new Response(bundle(),{headers:{'Content-Type':'application/zip'}}),'a'.repeat(64));
  assert.equal(page.skipped,1);assert.equal(page.snapshot?.blocks.length,1);
  await assert.rejects(()=>readRenderResponse(new Response(bundle(),{headers:{'Content-Type':'application/zip'}}),'b'.repeat(64)),/identity/);
  const old=await readRenderResponse(new Response(new Uint8Array([1,2,3]),{headers:{
    'Content-Type':'image/png','X-YomiScan-Blocks-Rendered':'2','X-YomiScan-Blocks-Skipped':'1'}}),'a'.repeat(64));
  assert.equal(old.rendered,2);assert.equal(old.snapshot,undefined);
});
