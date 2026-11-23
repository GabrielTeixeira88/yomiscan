import test from "node:test";
import assert from "node:assert/strict";
import {BACKEND_PORT_KEY,DEFAULT_BACKEND_PORT,backendBase,backendOrigin,backendPort,parseBackendOrigin,validBackendPort} from "../src/backend";

const storage=(value:unknown)=>({get:async(key:string)=>value===undefined?{}:{[key]:value}});

test("default backend port is not AnkiConnect's 8765",()=>{
  assert.equal(DEFAULT_BACKEND_PORT,47615);
  assert.notEqual(DEFAULT_BACKEND_PORT,8765);
  assert.equal(backendOrigin(DEFAULT_BACKEND_PORT),"http://127.0.0.1:47615");
});

test("backend port accepts only unprivileged integer ports",()=>{
  for(const port of [1024,8790,65535])assert.ok(validBackendPort(port));
  for(const port of [80,1023,65536,8790.5,"8790",null])assert.ok(!validBackendPort(port));
  assert.throws(()=>backendOrigin(80));
});

test("stored port is used; missing or invalid values fall back to the default",async()=>{
  assert.equal(await backendPort(storage(8790)),8790);
  assert.equal(await backendPort(storage(undefined)),DEFAULT_BACKEND_PORT);
  assert.equal(await backendPort(storage("8790")),DEFAULT_BACKEND_PORT);
  assert.equal(await backendPort(storage(22)),DEFAULT_BACKEND_PORT);
  assert.equal(await backendBase(storage(8790)),"http://127.0.0.1:8790");
  assert.equal(BACKEND_PORT_KEY,"backendPort");
});

test("offscreen accepts only a loopback origin with a valid port",()=>{
  assert.equal(parseBackendOrigin("http://127.0.0.1:8790"),"http://127.0.0.1:8790");
  for(const value of ["http://localhost:8790","https://127.0.0.1:8790","http://127.0.0.1:80","http://127.0.0.1:8790/api",
    "http://evil.example:8790","http://127.0.0.1:99999",undefined,42])
    assert.throws(()=>parseBackendOrigin(value));
});

import {documentKey} from "../src/navigation";
test("Study document identity ignores hash changes but not chapter navigation",()=>{
  const at=(href:string)=>{const url=new URL(href);return documentKey({origin:url.origin,pathname:url.pathname,search:url.search});};
  assert.equal(at("https://reader.example/ch/1?p=2#page-3"),at("https://reader.example/ch/1?p=2#page-9"));
  assert.notEqual(at("https://reader.example/ch/1"),at("https://reader.example/ch/2"));
  assert.notEqual(at("https://reader.example/read?ch=1"),at("https://reader.example/read?ch=2"));
});
