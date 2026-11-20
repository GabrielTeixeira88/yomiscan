import test from 'node:test';
import assert from 'node:assert/strict';
import {ChapterQueue} from '../src/chapter/model';

const MiB=1024*1024;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
type Result={url:string;bytes:number};
function fixture(budget=128*MiB) {
  const visible=new Set<object>(),freed:string[]=[],calls:number[]=[];
  let fail=false;
  const queue=new ChapterQueue<number,Result>({priority:p=>p.id,changed:()=>{},
    cache:{budget,size:r=>r.bytes,protected:p=>visible.has(p.key)},
    release:r=>{assert.ok(!freed.includes(r.url),'URL released twice');freed.push(r.url);},
    process:async p=>{calls.push(p.id);if(fail)throw new Error('offline');return {url:`${p.id}-${calls.length}`,bytes:p.source};}});
  return {queue,visible,freed,calls,setFail:(v:boolean)=>fail=v};
}

test('long chapter exceeds 128 MiB cumulatively without stopping; churn stays bounded',async()=>{
  const {queue,visible,freed,calls}=fixture();const keys=Array.from({length:80},()=>({}));
  visible.add(keys[0]);for(const key of keys)queue.register(key,'source',16*MiB);
  queue.start();await queue.idle();assert.equal(calls.length,80);
  assert.equal(queue.cacheStats().bytes,128*MiB);assert.equal(queue.cacheStats().evictions,72);
  assert.ok(queue.pages.get(keys[0])?.result);assert.equal(queue.pages.get(keys[1])?.state,'evicted');
  for(let i=1;i<60;i++){
    visible.clear();visible.add(keys[i]);queue.visible(keys[i]);await queue.idle();
    assert.ok(queue.pages.get(keys[i])?.result);assert.ok(queue.cacheStats().bytes<=128*MiB);
  }
  queue.dispose();assert.equal(queue.cacheStats().bytes,0);assert.equal(freed.length,calls.length);
});

test('LRU touch, offscreen eviction and export pins select only eligible results',async()=>{
  const {queue,freed}=fixture(30);const a={},b={},c={},d={},e={};
  for(const key of [a,b,c])queue.register(key,'v1',10);queue.start();await queue.idle();
  queue.visible(a);const unpin=queue.pin(b);
  queue.register(d,'v1',10);await queue.idle();assert.equal(queue.pages.get(c)?.state,'evicted');
  queue.register(e,'v1',10);await queue.idle();assert.equal(queue.pages.get(a)?.state,'evicted');
  assert.ok(queue.pages.get(b)?.result);unpin();unpin();queue.dispose();assert.equal(freed.length,5);
});

test('export retains a replaced result until unpin; clear and late unpin release once',async()=>{
  const {queue,freed}=fixture(30),key={};queue.register(key,'old',10);queue.start();await queue.idle();
  const unpin=queue.pin(key);queue.register(key,'new',10);await queue.idle();
  assert.deepEqual(freed,[]);assert.equal(queue.cacheStats().bytes,20);
  unpin();unpin();assert.deepEqual(freed,['1-1']);
  const last=queue.pin(key);queue.dispose();last();assert.equal(queue.cacheStats().bytes,0);assert.equal(freed.length,2);
});

test('refresh near capacity credits old bytes and protects old output on failure',async()=>{
  const f=fixture(20),a={},b={};f.visible.add(a);
  f.queue.register(a,'a',10);f.queue.register(b,'b',10);f.queue.start();await f.queue.idle();
  f.queue.refresh(a);await f.queue.idle();assert.equal(f.queue.cacheStats().bytes,20);
  assert.deepEqual(f.freed,['1-1']);const previous=f.queue.pages.get(a)?.result;
  f.setFail(true);f.queue.refresh(a);await f.queue.idle();assert.equal(f.queue.pages.get(a)?.result,previous);
  assert.match(f.queue.pages.get(a)!.error!,/previous translation retained/);f.queue.dispose();
});

test('protected capacity, oversize pages, failed restore and stop do not cause loops',async()=>{
  const f=fixture(10),a={},b={},huge={};f.visible.add(a);
  f.queue.register(a,'a',10);f.queue.register(b,'b',10);f.queue.register(huge,'huge',11);
  f.queue.start();await f.queue.idle();assert.equal(f.calls.length,3);
  assert.equal(f.queue.pages.get(b)?.state,'evicted');assert.equal(f.queue.pages.get(huge)?.state,'skipped');
  f.visible.clear();f.visible.add(b);f.setFail(true);f.queue.visible(b);await f.queue.idle();
  assert.equal(f.queue.pages.get(b)?.state,'failed');f.queue.visible(b);await tick();assert.equal(f.calls.length,4);
  f.queue.stop();f.queue.visible(a);await tick();assert.equal(f.calls.length,4);f.queue.dispose();
});
