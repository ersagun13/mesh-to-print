import test from 'node:test';
import assert from 'node:assert/strict';
import {parsePreview, buildOptions, number, bytes, dimensions, safeArtifactURL, JobGate, comparisonBounds} from '../lib.js';
function mesh({positions=[0,0,0,1,0,0,0,1,0],indices=[0,1,2]}={}) {
  const a=new ArrayBuffer(12+positions.length*4+indices.length*4), d=new DataView(a);
  new Uint8Array(a,0,4).set([77,83,72,49]); d.setUint32(4,positions.length/3,true);d.setUint32(8,indices.length/3,true);
  positions.forEach((v,i)=>d.setFloat32(12+i*4,v,true));indices.forEach((v,i)=>d.setUint32(12+positions.length*4+i*4,v,true));return a;
}
test('MSH1 exact lengths, little endian coordinates and index bounds',()=>{
 const m=parsePreview(mesh());assert.deepEqual([...m.indices],[0,1,2]);assert.equal(m.positions[3],1);assert.equal(m.triangleCount,1);
 assert.throws(()=>parsePreview(mesh().slice(0,-1)),/length/i);
 const bad=mesh();new DataView(bad).setUint32(48,3,true);assert.throws(()=>parsePreview(bad),/index/i);
 assert.throws(()=>parsePreview(mesh({positions:[0,0,0,Infinity,0,0,0,1,0]})),/finite/i);
 const wrong=mesh();new Uint8Array(wrong)[0]=0;assert.throws(()=>parsePreview(wrong),/MSH1/i);
});
test('game settings preserve explicit values and reject invalid numeric options',()=>{
 const o=buildOptions('play',{mode:'prepare',ratios:'0.5, 0.25, 0.1',error:'0.01',height:'',bottom_center:true});
 assert.deepEqual(o,{mode:'prepare',ratios:[0.5,0.25,0.1],error:0.01,height:null,bottom_center:true});
 for(const ratios of ['NaN,0.2,0.1','1.2,0.2,0.1','0.1,0.5,0.2'])assert.throws(()=>buildOptions('play',{mode:'prepare',ratios,error:'0.01',height:''}));
 assert.throws(()=>buildOptions('play',{mode:'prepare',ratios:'0.5,0.25,0.1',error:'Infinity',height:''}));
});
test('print settings retain mm bed axes and validate positive bounds and sample count',()=>{
 const input={mode:'analyze',units:'mm',size:'',bed_x:'256',bed_y:'220',bed_z:'250',wall:'1.2',overhang:'45',samples:'256',weld_tolerance:'0.00001'};
 assert.deepEqual(buildOptions('print',input),{mode:'analyze',units:'mm',size:null,bed:[256,220,250],wall:1.2,overhang:45,samples:256,weld_tolerance:0.00001,fill_holes_mm:null});
 assert.throws(()=>buildOptions('print',{...input,bed_z:'0'}));assert.throws(()=>buildOptions('print',{...input,samples:'1.5'}));assert.throws(()=>buildOptions('print',{...input,units:'yards'}));
});
test('missing and nonfinite measurements stay unavailable, real zero stays zero',()=>{
 assert.equal(number(undefined),'Unavailable');assert.equal(number(null),'Unavailable');assert.equal(number(NaN),'Unavailable');assert.equal(number(0),'0');assert.equal(bytes(null),'Unavailable');assert.equal(bytes(1024),'1 KiB');assert.equal(dimensions([1,2,3],'mm'),'1 × 2 × 3 mm');assert.equal(dimensions([1,null,3],'mm'),'Unavailable');
});
test('artifacts cannot link outside registered job files or execute scripts',()=>{
 const base='http://127.0.0.1:4000';assert.equal(safeArtifactURL('/api/jobs/abc/files/report.json','abc',base),'/api/jobs/abc/files/report.json');
 for(const url of ['javascript:alert(1)','https://other.test/api/jobs/abc/files/x','/api/jobs/other/files/x','/api/jobs/abc/files/../config','/api/jobs/abc/files/%2e%2e','/api/jobs/abc/files/a%2fb'])assert.equal(safeArtifactURL(url,'abc',base),null);
});
test('superseded jobs cannot win a late completion race',()=>{
 const gate=new JobGate(),a=gate.begin(),b=gate.begin();assert.equal(gate.current(a),false);assert.equal(gate.current(b),true);gate.cancel();assert.equal(gate.current(b),false);
});
test('comparison bounds preserve common scale across unequal candidates',()=>{
 const b=comparisonBounds([parsePreview(mesh()),parsePreview(mesh({positions:[-2,0,0,2,0,0,0,4,0]}))]);assert.deepEqual(b.center,[0,2,0]);assert.equal(b.radius,Math.sqrt(8));
});
test('issue overlays use validated indices only and stay bounded',async()=>{
 const {issueGeometry}=await import('../lib.js');const m=parsePreview(mesh());
 const o=issueGeometry(m,{issue_faces:[0,99,-1],issue_edges:[[0,1],[1,4],['0',2]]});assert.deepEqual([...o.faces],[0,1,2]);assert.deepEqual([...o.edges],[0,1]);
});
test('opt-in hole fill stays disabled unless explicitly checked',()=>{
 const input={mode:'repair',units:'mm',size:'',bed_x:256,bed_y:256,bed_z:256,wall:1.2,overhang:45,samples:256,weld_tolerance:0.00001,fill_holes:false,fill_holes_mm:'2'};
 assert.equal(buildOptions('print',input).fill_holes_mm,null);assert.equal(buildOptions('print',{...input,fill_holes:true}).fill_holes_mm,2);assert.throws(()=>buildOptions('print',{...input,fill_holes:true,fill_holes_mm:0}));
});
test('game ratio one and dimensions above engine bounds are rejected',()=>{
 const v={mode:'prepare',ratios:'0.5,0.25,0.1',error:0.01,height:''};assert.throws(()=>buildOptions('play',{...v,ratios:'1,0.5,0.25'}));assert.throws(()=>buildOptions('play',{...v,height:10001}));
});
test('small positive measurements never display a fabricated zero',()=>{
 assert.notEqual(number(0.00001),'0');assert.match(number(0.00001),/1/);
});
test('demo selection is load-only and cannot inherit repair or hole-filling consent',async()=>{
 const {selectionPolicy,loadDemoSelection}=await import('../lib.js');
 const unsafe={mode:'repair',units:'mm',fill_holes_mm:5};
 const fresh=selectionPolicy('print',unsafe);assert.equal(fresh.mode,'analyze');assert.equal(fresh.fill_holes_mm,null);assert.equal(fresh.fill_holes,false);
 assert.equal(selectionPolicy('print').mode,'analyze');assert.equal(selectionPolicy('play',{mode:'prepare'}).mode,'inspect');
 const events=[];await loadDemoSelection('print',async()=>{events.push('load');return {filename:'demo.stl',content_base64:'YQ==',options:unsafe};},(demo,policy)=>{events.push('select');assert.equal(demo.filename,'demo.stl');assert.equal(policy.fill_holes,false);assert.equal(policy.mode,'analyze');});
 assert.deepEqual(events,['load','select']);
});
test('presets reflect both ratios and geometric error',async()=>{
 const {identifyPreset}=await import('../lib.js');assert.equal(identifyPreset('0.5,0.25,0.1','0.01'),'balanced');assert.equal(identifyPreset('0.5,0.25,0.1','0.02'),'custom');assert.equal(identifyPreset('0.75,0.5,0.25','0.005'),'gentle');
});
test('print artifacts show dimensions_mm and missing bounds remain unavailable',async()=>{
 const {resultDimensions}=await import('../lib.js');assert.equal(resultDimensions('print',{dimensions_mm:[20,30,40]}),'20 × 30 × 40 mm');assert.equal(resultDimensions('print',{}),'Unavailable');assert.equal(resultDimensions('play',{dimensions:[1,2,3]}),'1 × 2 × 3 meters');
});
test('preview resource limits reject counts and bytes before allocating output arrays',()=>{
 for(const [product,vertices,triangles] of [['print',3000001,1],['print',3,1000001],['play',2000001,1],['play',3,2000001]]){const buffer=mesh();new DataView(buffer).setUint32(4,vertices,true);new DataView(buffer).setUint32(8,triangles,true);assert.throws(()=>parsePreview(buffer,product),/resource limit/i);}
 assert.throws(()=>parsePreview(new ArrayBuffer(48000013),'print'),/resource limit/i);
});
test('repair before and after diagnostics stay attached to their corresponding previews',async()=>{
 const {previewIssues}=await import('../lib.js'),before={issue_faces:[1],issue_edges:[[0,2]]},after={issue_faces:[3]};
 const report={...after,issue_preview:'after',repair:{before,after}};assert.equal(previewIssues(report,'before'),before);assert.equal(previewIssues(report,'after'),report);assert.equal(previewIssues({issue_preview:'after'},'before'),null);
});
