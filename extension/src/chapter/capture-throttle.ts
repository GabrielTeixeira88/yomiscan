/** Shared by Study and chapter capture, across tabs. Chrome allows at most 2/sec. */
export class CaptureThrottle {
  private tail:Promise<unknown>=Promise.resolve();
  private last=-Infinity;
  constructor(private now:()=>number=()=>Date.now(),
    private wait:(ms:number)=>Promise<void>=ms=>new Promise(resolve=>setTimeout(resolve,ms))) {}
  run<T>(capture:()=>Promise<T>):Promise<T> {
    const next=this.tail.then(async()=>{
      const delay=650-(this.now()-this.last);if(delay>0)await this.wait(delay);
      this.last=this.now();return capture();
    });
    this.tail=next.catch(()=>{});return next;
  }
}
