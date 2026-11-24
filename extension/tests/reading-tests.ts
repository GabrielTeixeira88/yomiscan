import test from "node:test";
import assert from "node:assert/strict";
import {parseReadingPage,stepBubble} from "../src/chapter/reading";

const token={surface:"猫",reading:"ネコ",lemma:"猫",dictionary_form:"猫",part_of_speech:"名詞",conjugation_type:null,conjugation_form:null,meanings:[]};
const block=(id:number,order:number,extra:Record<string,unknown>={})=>({id,region_ids:[id],reading_order:order,orientation:"vertical",
  bbox:{left:10*id,top:5,right:10*id+8,bottom:40},original_text:"猫",translation:"Cat",tokens:[token],units:[],grammar:[],
  confidence:.9,category:"bubble",status:"success",error_message:null,provenance:{engine:"opus-mt-ja-en"},...extra});
const page=(blocks:unknown[])=>({width:100,height:200,regions_detected:blocks.length,regions_filtered:0,text_blocks:blocks,
  processing:{ocr_ms:1,translation_ms:1,analysis_ms:1,total_ms:3,detection_ms:1}});

test("reading page: bubbles in reading order become study analyses without new OCR", () => {
  const result=parseReadingPage(page([block(2,1),block(1,0),block(3,2,{status:"filtered",tokens:[]}),block(4,3,{original_text:" ",tokens:[]})]),{width:100,height:200});
  assert.deepEqual(result.bubbles.map(b=>b.id),[1,2]);
  assert.equal(result.unreadable,2);
  assert.deepEqual(result.bubbles[0].box,{x:10,y:5,width:8,height:35});
  assert.equal(result.bubbles[0].analysis.translation,"Cat");
  assert.equal(result.bubbles[0].analysis.provenance?.analysis_origin,"page");
  assert.equal(result.bubbles[0].analysis.provenance?.engine,"opus-mt-ja-en");
});

test("reading page: rejects mismatched dimensions, boxes outside the page and malformed tokens", () => {
  assert.throws(()=>parseReadingPage(page([block(1,0)]),{width:101,height:200}),/dimensions/);
  assert.throws(()=>parseReadingPage(page([block(1,0,{bbox:{left:0,top:0,right:101,bottom:10}})])),/geometry/);
  assert.throws(()=>parseReadingPage(page([block(1,0,{bbox:{left:5,top:0,right:5,bottom:10}})])),/geometry/);
  assert.throws(()=>parseReadingPage(page([block(1,0,{tokens:[{surface:1}]})])),/token/);
  assert.throws(()=>parseReadingPage(page(Array.from({length:257},(_,i)=>block(1,i)))),/Invalid page analysis/);
  assert.throws(()=>parseReadingPage({width:0,height:1,text_blocks:[]}),/Invalid page analysis/);
});

test("J / K stepping crosses pages, skips empty pages and waits for unread ones", () => {
  const counts=[2,0,3,null,1];
  assert.deepEqual(stepBubble(counts,null,1),{page:0,bubble:0});
  assert.deepEqual(stepBubble(counts,null,-1),{page:4,bubble:0});
  assert.deepEqual(stepBubble(counts,{page:0,bubble:0},1),{page:0,bubble:1});
  assert.deepEqual(stepBubble(counts,{page:0,bubble:1},1),{page:2,bubble:0});
  assert.deepEqual(stepBubble(counts,{page:2,bubble:0},-1),{page:0,bubble:1});
  assert.deepEqual(stepBubble(counts,{page:2,bubble:2},1),{waiting:3});
  assert.deepEqual(stepBubble(counts,{page:4,bubble:0},-1),{waiting:3});
  assert.equal(stepBubble(counts,{page:4,bubble:0},1),null);
  assert.equal(stepBubble(counts,{page:0,bubble:0},-1),null);
  assert.equal(stepBubble([0,0],null,1),null);
});
