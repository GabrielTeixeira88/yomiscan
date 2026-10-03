import test from 'node:test';
import assert from 'node:assert/strict';
import {PageImageAcquirer,AcquisitionError,canvasPixels,type AcquisitionStrategies} from '../src/chapter/acquisition';
import {fetchSourceImage,imageHost} from '../src/chapter/source-fetch';
import {captureSegments,pixelSlice,withRestoredScroll} from '../src/chapter/stitching';
import {CaptureThrottle} from '../src/chapter/capture-throttle';
import type {MangaPageCandidate} from '../src/chapter/discovery';

const pixels={blob:new Blob(['pixels'],{type:'image/png'}),width:800,height:1100};
const candidate=(source='https://cdn.example/page.png')=>({source,width:800,height:1100,image:{}} as MangaPageCandidate);
const ok=async()=>pixels,fail=async()=>{throw new Error('restricted');};
const signal=()=>new AbortController().signal;

test('direct source acquisition succeeds without a canvas or screenshot',async()=>{
  const result=await new PageImageAcquirer({direct:ok,canvas:fail,viewport:fail,stitch:fail}).acquire(candidate(),signal());
  assert.equal(result.method,'direct-extension-fetch');assert.equal(result.attempts.length,1);
});
test('HTTP 403 and canvas security failures are retained when viewport fallback succeeds',async()=>{
  const result=await new PageImageAcquirer({direct:async()=>{throw new Error('HTTP 403');},
    canvas:async()=>{throw new DOMException('Tainted canvas','SecurityError');},viewport:ok,stitch:fail}).acquire(candidate(),signal());
  assert.equal(result.method,'viewport-capture');assert.equal(result.attempts[0].reason,'HTTP 403');
  assert.deepEqual(result.attempts.map(a=>a.success),[false,false,true]);
});
test('same-origin canvas remains a fallback when direct fetch is unavailable',async()=>{
  const result=await new PageImageAcquirer({direct:fail,canvas:ok,viewport:fail,stitch:fail}).acquire(candidate('https://reader.example/page.png'),signal());
  assert.equal(result.method,'canvas');
});
test('data/blob image sources use canvas without sending URLs to extension network fetch',async()=>{
  for(const source of ['data:image/png;base64,AA==','blob:https://reader.example/id']) {
    let direct=0;
    const result=await new PageImageAcquirer({direct:async()=>{direct++;return pixels;},canvas:ok,viewport:fail,stitch:fail}).acquire(candidate(source),signal());
    assert.equal(direct,0);assert.equal(result.method,'canvas');assert.equal(imageHost(source),null);
  }
});
test('all acquisition failures expose ordered diagnostics, including stitching failure',async()=>{
  await assert.rejects(()=>new PageImageAcquirer({direct:fail,canvas:fail,viewport:fail,stitch:fail}).acquire(candidate(),signal()),error=>{
    assert.ok(error instanceof AcquisitionError);assert.equal(error.attempts.length,4);
    assert.deepEqual(error.attempts.map(a=>a.method),['direct-extension-fetch','canvas','viewport-capture','stitched-capture']);return true;
  });
});
test('cancellation prevents advancing to a fallback',async()=>{
  const controller=new AbortController();let called=false;
  const strategies:AcquisitionStrategies={direct:async()=>{controller.abort();throw new Error('cancel');},canvas:async()=>{called=true;return pixels;},viewport:ok,stitch:ok};
  await assert.rejects(()=>new PageImageAcquirer(strategies).acquire(candidate(),controller.signal),{name:'AbortError'});
  assert.equal(called,false);
});
test('extension fetch preserves source MIME and credentials, checks permissions, rejects redirects',async()=>{
  let options:RequestInit|undefined;
  const request=(async(url,init)=>{assert.equal(url,'https://cdn.example/selected.webp');options=init;return new Response('webp',{headers:{'Content-Type':'image/webp'}});}) as typeof fetch;
  const blob=await fetchSourceImage('https://cdn.example/selected.webp',signal(),async host=>{assert.equal(host,'https://cdn.example/*');return true;},request);
  assert.equal(blob.type,'image/webp');assert.equal(options?.credentials,'include');assert.equal(options?.redirect,'error');
  await assert.rejects(()=>fetchSourceImage('https://cdn.example/selected.webp',signal(),async()=>false,request),/permission not granted/);
  assert.equal(imageHost('https://user:password@cdn.example/image'),null);
});
test('extension fetch reports authentication and type/size failures explicitly',async()=>{
  for(const status of [401,403,404])await assert.rejects(()=>fetchSourceImage('https://cdn.example/p',signal(),async()=>true,
    (async()=>new Response('',{status})) as typeof fetch),new RegExp(`HTTP ${status}`));
  await assert.rejects(()=>fetchSourceImage('https://cdn.example/p',signal(),async()=>true,
    (async()=>new Response('<html>',{headers:{'Content-Type':'text/html'}})) as typeof fetch),/content type/);
  await assert.rejects(()=>fetchSourceImage('https://cdn.example/p',signal(),async()=>true,
    (async()=>new Response('x',{headers:{'Content-Type':'image/png','Content-Length':'12000000'}})) as typeof fetch),/10 MiB/);
});
test('tall page plans and fractional-DPR pixel slices cover exactly once in order',()=>{
  for(const height of [1100,1100.5,503,2500])for(const scale of [1,1.25,1.5,2]) {
    const segments=captureSegments(height,500),slices=segments.map(s=>pixelSlice(s,scale));
    assert.equal(slices[0].y,0);
    for(let i=1;i<slices.length;i++)assert.equal(slices[i].y,slices[i-1].y+slices[i-1].height);
    assert.equal(slices.at(-1)!.y+slices.at(-1)!.height,Math.round(height*scale));
    assert.ok(segments.every(s=>s.height<=500));
  }
  assert.throws(()=>captureSegments(1000,10));assert.throws(()=>captureSegments(100000,500));
});
test('scroll position is restored after success, error and cancellation',async()=>{
  for(const failure of [undefined,new Error('capture failed'),new DOMException('cancelled','AbortError')]) {
    let position={x:12,y:456};
    const work=withRestoredScroll(()=>({...position}),(x,y)=>{position={x,y};},async()=>{position={x:0,y:999};if(failure)throw failure;return true;});
    if(failure)await assert.rejects(()=>work);else assert.equal(await work,true);
    assert.deepEqual(position,{x:12,y:456});
  }
});
test('global screenshot throttle spaces captures and survives capture failure',async()=>{
  let now=0;const times:number[]=[];
  const throttle=new CaptureThrottle(()=>now,async ms=>{now+=ms;});
  const jobs=[0,1,2,3].map(i=>throttle.run(async()=>{times.push(now);if(i===1)throw new Error('capture failed');return i;}));
  const results=await Promise.allSettled(jobs);
  assert.equal(results[1].status,'rejected');assert.deepEqual(times,[0,650,1300,1950]);
});
test('permission grant is checked again on retry without caching denial',async()=>{
  let granted=false;
  const request=(async()=>new Response('png',{headers:{'Content-Type':'image/png'}})) as typeof fetch;
  const acquire=()=>fetchSourceImage('https://cdn.example/page.png',signal(),async()=>granted,request);
  await assert.rejects(acquire,/permission/);granted=true;assert.equal((await acquire()).type,'image/png');
});
test('DOM canvas reads selected source and releases backing pixels on success or security failure',async()=>{
  const savedDocument=globalThis.document,savedStyle=globalThis.getComputedStyle;
  let restricted=false,drawn:unknown;
  const canvas={width:0,height:0,getContext:()=>({drawImage:(image:unknown)=>{drawn=image;}}),toBlob:(callback:(blob:Blob)=>void)=>{
    if(restricted)throw new DOMException('Tainted','SecurityError');callback(pixels.blob);
  }};
  globalThis.document={createElement:()=>canvas} as unknown as Document;
  globalThis.getComputedStyle=(()=>({transform:'none'})) as unknown as typeof getComputedStyle;
  const image={complete:true,naturalWidth:800,currentSrc:'https://cdn.example/selected.png',src:'placeholder'} as HTMLImageElement;
  const page={image,source:image.currentSrc,width:800,height:1100};
  try {
    assert.equal((await canvasPixels(page,signal())).blob,pixels.blob);assert.equal(drawn,image);assert.equal(canvas.width,0);
    restricted=true;await assert.rejects(()=>canvasPixels(page,signal()),/cross-origin restricted/);assert.equal(canvas.height,0);
  } finally {globalThis.document=savedDocument;globalThis.getComputedStyle=savedStyle;}
});
