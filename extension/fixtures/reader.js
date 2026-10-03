// Original synthetic fixtures, generated locally. No third-party manga assets.
let count=0;
function page(number) {
  const canvas=document.createElement("canvas");canvas.width=800;canvas.height=1100;
  const ctx=canvas.getContext("2d");ctx.fillStyle="white";ctx.fillRect(0,0,800,1100);
  ctx.strokeStyle="#151515";ctx.lineWidth=5;ctx.strokeRect(20,20,760,500);ctx.strokeRect(20,540,760,540);
  ctx.fillStyle="#ddd";ctx.fillRect(40,320,710,170);ctx.beginPath();ctx.arc(210,300,95,0,Math.PI*2);ctx.stroke();
  ctx.beginPath();ctx.ellipse(570,200,160,130,0,0,Math.PI*2);ctx.stroke();
  ctx.font="40px sans-serif";ctx.fillStyle="#111";ctx.fillText("でも大丈夫",460,200);
  ctx.font="32px sans-serif";ctx.fillText(`Synthetic page ${number}`,70,630);ctx.fillText("これは何？",460,790);
  ctx.fillStyle=`rgb(${number},0,0)`;ctx.fillRect(0,0,8,8); // Test identity survives srcset density scaling.
  return canvas.toDataURL("image/png");
}
function append(lazy=false) {
  const image=document.createElement("img");image.id=`page-${++count}`;image.alt=`Synthetic manga page ${count}`;
  image.width=800;image.height=1100;
  if(lazy){image.dataset.src=page(count);image.style.minHeight="688px";}else image.src=page(count);
  document.querySelector("main").append(image);return image;
}
const single=new URLSearchParams(location.search).has("single");
for(let i=0;i<(single?1:5);i++)append();
if(!single)append(true);
document.querySelector("#page-1").srcset=`${page(1)} 1x, ${page(1)} 2x`;
document.querySelector("#avatar").src=page(0);document.querySelector("#logo").src=page(0);
document.querySelector("#append").onclick=()=>append();
document.querySelector("#lazy").onclick=()=>{const image=document.querySelector("[data-src]");if(image){image.src=image.dataset.src;delete image.dataset.src;}};
document.querySelector("#swap").onclick=()=>{const image=document.querySelector("#page-1");image.removeAttribute("srcset");image.src=page(99);};
document.querySelector("#navigate").onclick=()=>history.pushState({},"",`?chapter=${Date.now()}`);
