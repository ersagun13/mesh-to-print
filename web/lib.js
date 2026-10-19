// Small, dependency-free boundary between untrusted input and the workspace.
export const PREVIEW_LIMITS=Object.freeze({play:Object.freeze({vertices:2000000,triangles:2000000,bytes:48000012}),print:Object.freeze({vertices:3000000,triangles:1000000,bytes:48000012})});
export function parsePreview(buffer,product='play') {
  const limits=PREVIEW_LIMITS[product];if(!limits)throw new Error('Unknown preview product.');
  if(buffer instanceof ArrayBuffer&&buffer.byteLength>limits.bytes)throw new Error('Preview resource limit exceeded.');
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 12) throw new Error('Invalid MSH1 preview header.');
  const d=new DataView(buffer);
  if(d.getUint32(0,false)!==0x4d534831)throw new Error('Invalid MSH1 preview magic.');
  const vertexCount=d.getUint32(4,true),triangleCount=d.getUint32(8,true);
  if(vertexCount>limits.vertices||triangleCount>limits.triangles)throw new Error('Preview resource limit exceeded.');
  if(!vertexCount||!triangleCount||buffer.byteLength!==12+vertexCount*12+triangleCount*12)throw new Error('Invalid preview length or empty geometry.');
  const positions=new Float32Array(vertexCount*3),indices=new Uint32Array(triangleCount*3);
  for(let i=0;i<positions.length;i++){const v=d.getFloat32(12+i*4,true);if(!Number.isFinite(v))throw new Error('Preview positions must be finite.');positions[i]=v;}
  for(let i=0;i<indices.length;i++){const v=d.getUint32(12+positions.length*4+i*4,true);if(v>=vertexCount)throw new Error('Preview index is outside its vertex range.');indices[i]=v;}
  return {positions,indices,vertexCount,triangleCount};
}
function finite(value,label,min,max,integer=false){
  if(value===null||value===undefined||String(value).trim()==='')throw new Error(`${label} is required.`);
  const n=Number(value);if(!Number.isFinite(n)||n<min||n>max||(integer&&!Number.isInteger(n)))throw new Error(`${label} must be ${integer?'a whole number':'a number'} from ${min} to ${max}.`);return n;
}
export function buildOptions(product,v){
 if(product==='play'){
  if(!['inspect','prepare'].includes(v.mode))throw new Error('Choose inspect or prepare.');
  const ratios=String(v.ratios).split(',').map(x=>finite(x,'Triangle ratios',0,1));
  if(ratios.length!==3||ratios.some((x,i)=>x<=0||x>=1||(i&&x>=ratios[i-1])))throw new Error('Enter three decreasing triangle ratios, for example 0.5, 0.25, 0.1.');
  return {mode:v.mode,ratios,error:finite(v.error,'Relative error',0,1),height:v.height===''?null:finite(v.height,'Longest dimension',0.000001,10000),bottom_center:v.bottom_center===true};
 }
 if(!['analyze','repair'].includes(v.mode))throw new Error('Choose analyze or repair.');
 if(v.fill_holes===true&&v.mode!=='repair')throw new Error('Hole filling requires explicit repair mode.');
 if(!['mm','cm','m','in'].includes(v.units))throw new Error('Choose an input unit.');
 return {mode:v.mode,units:v.units,size:v.size===''?null:finite(v.size,'Target size',0.000001,10000000),bed:['x','y','z'].map(k=>finite(v['bed_'+k],'Build volume',0.000001,10000000)),wall:finite(v.wall,'Wall threshold',0.000001,10000),overhang:finite(v.overhang,'Overhang angle',0,90),samples:finite(v.samples,'Thickness samples',0,4096,true),weld_tolerance:finite(v.weld_tolerance,'Weld tolerance',0.000000001,1),fill_holes_mm:v.fill_holes===true?finite(v.fill_holes_mm,'Maximum hole diameter',0.000001,10000):null};
}
export function number(v){return typeof v==='number'&&Number.isFinite(v)?new Intl.NumberFormat('en',v!==0&&Math.abs(v)<0.001?{maximumSignificantDigits:4}:{maximumFractionDigits:3}).format(v):'Unavailable';}
export function bytes(v){if(typeof v!=='number'||!Number.isFinite(v)||v<0)return 'Unavailable';if(v<1024)return `${number(v)} B`;const i=Math.min(3,Math.floor(Math.log(v)/Math.log(1024)));return `${number(v/1024**i)} ${['B','KiB','MiB','GiB'][i]}`;}
export function dimensions(v,unit){return Array.isArray(v)&&v.length===3&&v.every(x=>typeof x==='number'&&Number.isFinite(x))?`${v.map(number).join(' × ')}${unit?' '+unit:''}`:'Unavailable';}
export function safeArtifactURL(value,jobId,base){
 try{if(typeof value!=='string'||!jobId)return null;const u=new URL(value,base),b=new URL(base),prefix=`/api/jobs/${encodeURIComponent(jobId)}/files/`;
 if(u.origin!==b.origin||!u.pathname.startsWith(prefix)||u.search||u.hash)return null;
 const name=decodeURIComponent(u.pathname.slice(prefix.length));if(!name||name==='.'||name==='..'||/[\\/\x00-\x1f]/.test(name))return null;return u.pathname;
 }catch{return null;}
}
export class JobGate{constructor(){this.generation=0;}begin(){return ++this.generation;}current(id){return id===this.generation;}cancel(){this.generation++;}}
export function comparisonBounds(meshes){
 const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];let found=false;
 for(const mesh of meshes.filter(Boolean))for(let i=0;i<mesh.positions.length;i++){found=true;const a=i%3;lo[a]=Math.min(lo[a],mesh.positions[i]);hi[a]=Math.max(hi[a],mesh.positions[i]);}
 if(!found)return {center:[0,0,0],radius:1};const center=lo.map((v,i)=>(v+hi[i])/2),radius=Math.hypot(...lo.map((v,i)=>(hi[i]-v)/2));return {center,radius:Math.max(radius,1e-9)};
}
export function issueGeometry(mesh,report){
 const faces=[],edges=[];
 for(const i of (Array.isArray(report.issue_faces)?report.issue_faces:[]).slice(0,5000))if(Number.isInteger(i)&&i>=0&&i<mesh.triangleCount)faces.push(...mesh.indices.subarray(i*3,i*3+3));
 for(const e of (Array.isArray(report.issue_edges)?report.issue_edges:[]).slice(0,5000))if(Array.isArray(e)&&e.length===2&&e.every(i=>Number.isInteger(i)&&i>=0&&i<mesh.vertexCount))edges.push(...e);
 return {faces:new Uint32Array(faces),edges:new Uint32Array(edges)};
}

// Source changes always require a fresh, explicit processing choice.
export function selectionPolicy(product,options={}){
 return {...options,mode:product==='print'?'analyze':'inspect',fill_holes:false,fill_holes_mm:null};
}
// Loading a demo has no processing side effect. Only the form submit starts a job.
export async function loadDemoSelection(product,fetchDemo,select){
 const demo=await fetchDemo();
 if(!demo||typeof demo.filename!=='string'||typeof demo.content_base64!=='string')throw new Error('Demo response is incomplete.');
 await select(demo,selectionPolicy(product,demo.options));
}
export function identifyPreset(ratios,error){
 const values=String(ratios).split(',').map(Number),e=Number(error);
 for(const [name,expected,bound] of [['balanced',[0.5,0.25,0.1],0.01],['gentle',[0.75,0.5,0.25],0.005]])if(values.length===3&&values.every((v,i)=>v===expected[i])&&e===bound)return name;
 return 'custom';
}
export function resultDimensions(product,result){return product==='print'?dimensions(result.dimensions_mm,'mm'):dimensions(result.dimensions,result.units||'meters');}
export function previewIssues(report,side){
 if(report?.issue_preview===side)return report;
 return side==='before'&&report?.repair?.before?report.repair.before:null;
}
