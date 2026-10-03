import test from "node:test";
import assert from "node:assert/strict";
import {ChapterQueue,SkipPage,WaitForViewport,viewportPriority} from "../src/chapter/model";
import {candidateReason,GenericPageDiscovery} from "../src/chapter/discovery";
import {CHUNK,encodeChunk,decodeChunk} from "../src/chapter/wire";

const facts={width:800,height:1100,displayedWidth:500,displayedHeight:688,visible:true,excluded:false,source:"blob:page"};
test("chapter candidates retain full pages and reject icons, ads, hidden and extreme strips",()=>{
  assert.equal(candidateReason(facts),null);
  for(const change of [{width:80},{height:100},{displayedWidth:100},{visible:false},{excluded:true},{source:""},{width:9000}])
    assert.ok(candidateReason({...facts,...change}));
});
test("viewport ordering is visible, below, above, distant",()=>{
  const priority=(top:number,bottom:number)=>viewportPriority(top,bottom,800);
  assert.equal(priority(0,1000),0);assert.equal(priority(-200,100),0);
  assert.ok(priority(810,1800)<priority(-400,-10));
  assert.ok(priority(-400,-10)<priority(5000,6000));
});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test("chapter queue prioritizes visible pages, serializes, deduplicates and caches toggles",async()=>{
  const seen:number[]=[],released:string[]=[];
  let active=0,max=0;
  const queue=new ChapterQueue<number,string>({priority:p=>p.source,release:r=>released.push(r),changed:()=>{},
    process:async p=>{max=Math.max(max,++active);seen.push(p.source);await tick();active--;return `url${p.id}`;}});
  const a={},b={};queue.register(a,"a",5);queue.register(b,"b",0);queue.register(b,"b",0);
  queue.start();await queue.idle();
  assert.deepEqual(seen,[0,5]);assert.equal(max,1);assert.equal(queue.pages.size,2);
  queue.setView("original");queue.setView("english");await tick();assert.equal(seen.length,2);
  queue.dispose();assert.equal(released.length,2);assert.equal(queue.pages.size,0);
});
test("page failures and skips are isolated and explicitly retried",async()=>{
  let fail=true;
  const queue=new ChapterQueue<number,string>({priority:p=>p.id,release:()=>{},changed:()=>{},process:async p=>{
    if(fail&&p.source===1)throw new Error("offline");if(fail&&p.source===2)throw new SkipPage("cors");return "ok";}});
  for(const n of [1,2,3])queue.register({},String(n),n);
  queue.start();await queue.idle();assert.deepEqual([...queue.pages.values()].map(p=>p.state),["failed","skipped","translated"]);
  fail=false;queue.retry();await queue.idle();assert.ok([...queue.pages.values()].every(p=>p.state==="translated"));
  assert.deepEqual([...queue.pages.values()].map(p=>p.attempts),[2,2,1]);queue.dispose();
});
test("stop prevents queued work, preserves current result; resume accepts lazy pages",async()=>{
  let release!:()=>void;let calls=0;
  const queue=new ChapterQueue<number,string>({priority:p=>p.id,release:()=>{},changed:()=>{},process:async()=>{
    calls++;if(calls===1)await new Promise<void>(r=>release=r);return "cached";}});
  queue.register({},"one",1);queue.register({},"two",2);queue.start();await tick();queue.stop();release();await queue.idle();
  assert.equal(calls,1);assert.deepEqual([...queue.pages.values()].map(p=>p.state),["translated","skipped"]);
  queue.start();await queue.idle();queue.register({},"lazy",3);await tick();await queue.idle();assert.equal(calls,3);queue.dispose();
});
test("reused DOM source invalidates cached output; stale in-flight results are released",async()=>{
  let release!:()=>void;const freed:string[]=[];
  const queue=new ChapterQueue<string,string>({priority:()=>0,release:r=>freed.push(r),changed:()=>{},process:async p=>{
    if(p.identity==="old")await new Promise<void>(r=>release=r);return p.identity;}});
  const element={};queue.register(element,"old","first");queue.start();await tick();queue.register(element,"new","second");release();await queue.idle();
  assert.deepEqual(freed,["old"]);assert.equal(queue.pages.get(element)?.result,"new");
  queue.register(element,"third","third");assert.deepEqual(freed,["old","new"]);await tick();await queue.idle();
  queue.remove(element);assert.deepEqual(freed,["old","new","third"]);queue.dispose();
});
test("destroy aborts in-flight work and releases late results without restarting",async()=>{
  let release!:()=>void,signal!:AbortSignal;const freed:string[]=[];
  const queue=new ChapterQueue<number,string>({priority:()=>0,release:r=>freed.push(r),changed:()=>{},process:async(_,s)=>{
    signal=s;await new Promise<void>(r=>release=r);return "late";}});
  queue.register({},"a",1);queue.start();await tick();queue.dispose();assert.ok(signal.aborted);release();await queue.idle();
  queue.start();assert.deepEqual(freed,["late"]);assert.equal(queue.pages.size,0);
});
test("image transport chunks round-trip binary without giant JSON arrays",async()=>{
  const bytes=Uint8Array.from({length:CHUNK},(_,i)=>i%256);
  assert.deepEqual(decodeChunk(await encodeChunk(new Blob([bytes]))),bytes);
  assert.throws(()=>decodeChunk("x".repeat(CHUNK*2)));assert.throws(()=>decodeChunk(null));
});
test("restricted offscreen pages retry when fully visible, with a bounded automatic limit",async()=>{
  const key={};let calls=0;
  const queue=new ChapterQueue<number,string>({priority:()=>0,release:()=>{},changed:()=>{},process:async()=>{calls++;throw new WaitForViewport("show page");}});
  queue.register(key,"a",1);queue.start();await queue.idle();
  for(let i=0;i<5;i++){queue.visible(key);await tick();await queue.idle();}
  assert.equal(calls,3);queue.stop();queue.visible(key);await tick();assert.equal(calls,3);queue.dispose();
});
test("generic discovery chooses stacked reader over unrelated columns and uses currentSrc",()=>{
  const original=globalThis.getComputedStyle;
  globalThis.getComputedStyle=(()=>({visibility:"visible",display:"block",opacity:"1"})) as unknown as typeof getComputedStyle;
  function image(x:number,y:number,excluded=false):HTMLImageElement {
    return {naturalWidth:800,naturalHeight:1100,complete:true,isConnected:true,currentSrc:`blob:${x}-${y}`,src:"placeholder",alt:"",id:"",parentElement:null,
      closest:()=>excluded?{}:null,getAttribute:()=>"",getBoundingClientRect:()=>({left:x,right:x+500,top:y,bottom:y+688,width:500,height:688})} as unknown as HTMLImageElement;
  }
  try {
    const first=image(100,0),second=image(100,700),unrelated=image(700,0),logo=image(100,1400,true);
    const result=new GenericPageDiscovery().discover({images:[first,second,unrelated,logo]} as unknown as Document);
    assert.deepEqual(result.candidates.map(c=>c.image),[first,second]);assert.equal(result.candidates[0].source,first.currentSrc);
    assert.equal(result.decisions.filter(d=>!d.accepted).length,2);
  } finally {globalThis.getComputedStyle=original;}
});
