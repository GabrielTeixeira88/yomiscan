/** Small stored-ZIP boundary: fixed filenames, CRC validation, no compression or dependencies. */
export const MAX_ZIP=48*1024*1024;
export interface ZipEntry {name:string;data:Uint8Array<ArrayBuffer>}
const encoder=new TextEncoder(),decoder=new TextDecoder('utf-8',{fatal:true});
const table=Uint32Array.from({length:256},(_,n)=>{for(let i=0;i<8;i++)n=(n&1)?0xedb88320^(n>>>1):n>>>1;return n>>>0;});
function crc32(data:Uint8Array):number {let crc=0xffffffff;for(const b of data)crc=table[(crc^b)&255]^(crc>>>8);return (crc^0xffffffff)>>>0;}
function safeName(name:string):boolean {return /^(?:optional\/)?[a-z][a-z0-9.-]*$/.test(name) && !name.includes('..');}
export function packZip(entries:ZipEntry[],limit=MAX_ZIP):Blob {
  if(entries.length>8 || new Set(entries.map(e=>e.name)).size!==entries.length)throw new Error('Invalid ZIP entries');
  let offset=0;const parts:BlobPart[]=[],central:Uint8Array<ArrayBuffer>[]=[];
  for(const {name,data} of entries) {
    if(!safeName(name))throw new Error('Unsafe ZIP path');
    const filename=encoder.encode(name),crc=crc32(data),header=new Uint8Array(30+filename.length);
    const view=new DataView(header.buffer);
    view.setUint32(0,0x04034b50,true);view.setUint16(4,20,true);view.setUint16(6,0x800,true);
    view.setUint16(12,33,true);view.setUint32(14,crc,true);view.setUint32(18,data.length,true);view.setUint32(22,data.length,true);
    view.setUint16(26,filename.length,true);header.set(filename,30);
    const directory=new Uint8Array(46+filename.length),dv=new DataView(directory.buffer);
    dv.setUint32(0,0x02014b50,true);dv.setUint16(4,20,true);dv.setUint16(6,20,true);dv.setUint16(8,0x800,true);
    dv.setUint16(14,33,true);dv.setUint32(16,crc,true);dv.setUint32(20,data.length,true);dv.setUint32(24,data.length,true);
    dv.setUint16(28,filename.length,true);dv.setUint32(42,offset,true);directory.set(filename,46);
    offset+=header.length+data.length;
    if(offset+central.reduce((n,c)=>n+c.length,0)+directory.length+22>limit)throw new Error('ZIP size limit exceeded');
    parts.push(header,data);central.push(directory);
  }
  const directorySize=central.reduce((n,c)=>n+c.length,0),end=new Uint8Array(22),ev=new DataView(end.buffer);
  ev.setUint32(0,0x06054b50,true);ev.setUint16(8,entries.length,true);ev.setUint16(10,entries.length,true);
  ev.setUint32(12,directorySize,true);ev.setUint32(16,offset,true);
  return new Blob([...parts,...central,end],{type:'application/zip'});
}
export async function unpackZip(blob:Blob,limit=MAX_ZIP):Promise<Map<string,Uint8Array<ArrayBuffer>>> {
  if(blob.size<22 || blob.size>limit)throw new Error('ZIP size limit or truncated archive');
  const buffer=await blob.arrayBuffer(),data=new Uint8Array(buffer),view=new DataView(buffer),end=data.length-22;
  const u16=(n:number)=>view.getUint16(n,true),u32=(n:number)=>view.getUint32(n,true);
  if(u32(end)!==0x06054b50 || u16(end+4)!==0 || u16(end+6)!==0 || u16(end+20)!==0 ||
    u16(end+8)!==u16(end+10) || u16(end+10)>8)throw new Error('Invalid ZIP directory');
  let cursor=u32(end+16);const directoryStart=cursor;
  if(cursor+u32(end+12)!==end)throw new Error('Invalid ZIP directory size');
  const result=new Map<string,Uint8Array<ArrayBuffer>>();
  let previousEnd=0;
  for(let i=0;i<u16(end+10);i++) {
    if(cursor+46>end || u32(cursor)!==0x02014b50)throw new Error('Invalid ZIP entry');
    const flags=u16(cursor+8),size=u32(cursor+24),nameLength=u16(cursor+28),local=u32(cursor+42);
    const next=cursor+46+nameLength+u16(cursor+30)+u16(cursor+32);
    if((flags!==0&&flags!==0x800) || u16(cursor+10)!==0 || u32(cursor+20)!==size || next>end ||
      local!==previousEnd || local+30>directoryStart)throw new Error('Unsupported ZIP layout');
    const name=decoder.decode(data.subarray(cursor+46,cursor+46+nameLength));
    if(!safeName(name) || result.has(name) || u32(local)!==0x04034b50 || u16(local+6)!==flags ||
      u16(local+8)!==0 || u32(local+14)!==u32(cursor+16) || u32(local+18)!==size || u32(local+22)!==size ||
      u16(local+26)!==nameLength)throw new Error('Invalid ZIP path/header');
    const start=local+30+u16(local+26)+u16(local+28);
    if(start+size>directoryStart || decoder.decode(data.subarray(local+30,local+30+nameLength))!==name)throw new Error('Invalid ZIP bounds');
    const bytes=data.slice(start,start+size);
    if(crc32(bytes)!==u32(cursor+16))throw new Error('ZIP CRC mismatch');
    result.set(name,bytes);cursor=next;previousEnd=start+size;
  }
  if(cursor!==end || previousEnd!==directoryStart)throw new Error('Invalid ZIP trailing data');
  return result;
}
