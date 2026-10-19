import {comparisonBounds,issueGeometry,previewIssues} from './lib.js';
const vertex=`#version 300 es
in vec3 position;
uniform vec3 center;
uniform float radius, yaw, pitch, cameraDistance, aspect;
uniform bool overlay;
out vec3 point;
void main(){
 vec3 p=(position-center)/radius;
 float cy=cos(yaw),sy=sin(yaw),cp=cos(pitch),sp=sin(pitch);
 vec3 q=vec3(cy*p.x+sy*p.z,p.y,-sy*p.x+cy*p.z);
 point=vec3(q.x,cp*q.y-sp*q.z,sp*q.y+cp*q.z);
 float z=point.z-cameraDistance;
 gl_Position=vec4(point.x*2.41421356/aspect,point.y*2.41421356,-1.0002*z-0.020002,-z);
 if(overlay)gl_Position.z-=0.0015*gl_Position.w;
}`;
const fragment=`#version 300 es
precision highp float;
in vec3 point;
uniform vec3 color;
uniform bool overlay;
out vec4 outColor;
void main(){
 vec3 n=normalize(cross(dFdx(point),dFdy(point)));
 float light=0.38+0.62*abs(dot(n,normalize(vec3(-0.4,0.8,0.6))));
 outColor=vec4(color*(overlay?1.0:light),1.0);
}`;
function shader(gl,type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error('Geometry shader could not compile.');return s;}
class Surface{
 constructor(canvas,camera,onChange,color){
  this.canvas=canvas;this.camera=camera;this.color=color;this.resources=[];
  try{this.gl=canvas.getContext('webgl2',{alpha:true,antialias:true});if(!this.gl)throw new Error('WebGL2 unavailable.');const g=this.gl,p=g.createProgram();
   const vs=shader(g,g.VERTEX_SHADER,vertex),fs=shader(g,g.FRAGMENT_SHADER,fragment);g.attachShader(p,vs);g.attachShader(p,fs);g.linkProgram(p);g.deleteShader(vs);g.deleteShader(fs);if(!g.getProgramParameter(p,g.LINK_STATUS))throw new Error('Geometry shader could not link.');this.program=p;
   this.uniforms=Object.fromEntries(['center','radius','yaw','pitch','cameraDistance','aspect','color','overlay'].map(k=>[k,g.getUniformLocation(p,k)]));this.attribute=g.getAttribLocation(p,'position');
  }catch(e){this.fail(e.message);}
  new ResizeObserver(()=>this.draw()).observe(canvas);
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();this.fail('Graphics context lost. Reload the page to restore the preview.');});
  canvas.addEventListener('pointerdown',e=>{if(!this.gl)return;canvas.focus();canvas.setPointerCapture(e.pointerId);this.drag={id:e.pointerId,x:e.clientX,y:e.clientY};});
  canvas.addEventListener('pointermove',e=>{if(!this.drag||this.drag.id!==e.pointerId)return;camera.yaw+=(e.clientX-this.drag.x)*0.009;camera.pitch=Math.max(-1.5,Math.min(1.5,camera.pitch+(e.clientY-this.drag.y)*0.009));this.drag={id:e.pointerId,x:e.clientX,y:e.clientY};onChange();});
  const end=()=>{this.drag=null;};canvas.addEventListener('pointerup',end);canvas.addEventListener('pointercancel',end);canvas.addEventListener('lostpointercapture',end);
  canvas.addEventListener('wheel',e=>{if(!this.mesh)return;e.preventDefault();camera.distance=Math.max(1.5,Math.min(25,camera.distance*Math.exp(e.deltaY*0.001)));onChange();},{passive:false});
  canvas.addEventListener('keydown',e=>{const step=0.12;if(e.key==='ArrowLeft')camera.yaw-=step;else if(e.key==='ArrowRight')camera.yaw+=step;else if(e.key==='ArrowUp')camera.pitch=Math.max(-1.5,camera.pitch-step);else if(e.key==='ArrowDown')camera.pitch=Math.min(1.5,camera.pitch+step);else if(['+','='].includes(e.key))camera.distance=Math.max(1.5,camera.distance/1.1);else if(e.key==='-')camera.distance=Math.min(25,camera.distance*1.1);else if(e.key==='Home')Object.assign(camera,{yaw:0.55,pitch:-0.25,distance:3.7});else return;e.preventDefault();onChange();});
 }
 fail(message){this.gl=null;this.canvas.hidden=true;const fallback=this.canvas.parentElement.querySelector('.canvas-fallback');fallback.hidden=false;fallback.textContent=message+' Measurements and downloads remain available.';}
 buffer(data){const g=this.gl,b=g.createBuffer();this.resources.push(b);g.bindBuffer(g.ELEMENT_ARRAY_BUFFER,b);g.bufferData(g.ELEMENT_ARRAY_BUFFER,data,g.STATIC_DRAW);return {buffer:b,count:data.length};}
 set(mesh,bounds,report){
  this.mesh=mesh;this.bounds=bounds;if(!this.gl)return;const g=this.gl;this.resources.forEach(b=>g.deleteBuffer(b));this.resources=[];if(!mesh){this.draw();return;}
  this.position=g.createBuffer();this.resources.push(this.position);g.bindBuffer(g.ARRAY_BUFFER,this.position);
  // Normalize in JS before float32 upload to keep very large/small valid models visible.
  const p=new Float32Array(mesh.positions.length);for(let i=0;i<p.length;i++)p[i]=(mesh.positions[i]-bounds.center[i%3])/bounds.radius;
  g.bufferData(g.ARRAY_BUFFER,p,g.STATIC_DRAW);this.triangles=this.buffer(mesh.indices);const o=issueGeometry(mesh,report||{});this.faces=this.buffer(o.faces);this.edges=this.buffer(o.edges);this.draw();
 }
 draw(){
  if(!this.gl)return;const g=this.gl,c=this.canvas,dpr=Math.min(window.devicePixelRatio||1,2),w=Math.max(1,Math.round(c.clientWidth*dpr)),h=Math.max(1,Math.round(c.clientHeight*dpr));if(c.width!==w||c.height!==h){c.width=w;c.height=h;}
  g.viewport(0,0,w,h);g.clearColor(0,0,0,0);g.clear(g.COLOR_BUFFER_BIT|g.DEPTH_BUFFER_BIT);if(!this.mesh)return;
  g.enable(g.DEPTH_TEST);g.useProgram(this.program);g.bindBuffer(g.ARRAY_BUFFER,this.position);g.enableVertexAttribArray(this.attribute);g.vertexAttribPointer(this.attribute,3,g.FLOAT,false,0,0);
  const u=this.uniforms;g.uniform3fv(u.center,[0,0,0]);g.uniform1f(u.radius,1);g.uniform1f(u.yaw,this.camera.yaw);g.uniform1f(u.pitch,this.camera.pitch);g.uniform1f(u.cameraDistance,this.camera.distance);g.uniform1f(u.aspect,w/h);
  const draw=(indices,mode,color,overlay)=>{if(!indices?.count)return;g.uniform3fv(u.color,color);g.uniform1i(u.overlay,overlay?1:0);g.bindBuffer(g.ELEMENT_ARRAY_BUFFER,indices.buffer);g.drawElements(mode,indices.count,g.UNSIGNED_INT,0);};
  draw(this.triangles,g.TRIANGLES,this.color,false);if(this.camera.issues){draw(this.faces,g.TRIANGLES,[1,0.42,0.12],true);draw(this.edges,g.LINES,[1,0.74,0.2],true);}
 }
}
export class ComparisonViewer{
 constructor(before,after,product){this.camera={yaw:0.55,pitch:-0.25,distance:3.7,issues:true};const draw=()=>this.draw();this.surfaces=[new Surface(before,this.camera,draw,product==='play'?[0.58,0.69,0.74]:[0.56,0.54,0.50]),new Surface(after,this.camera,draw,product==='play'?[0.24,0.82,0.70]:[0.83,0.48,0.27])];}
 set(before,after,report){const bounds=comparisonBounds([before,after]);this.surfaces[0].set(before,bounds,previewIssues(report,'before'));this.surfaces[1].set(after,bounds,previewIssues(report,'after'));this.reset();}
 draw(){this.surfaces.forEach(s=>s.draw());}
 reset(){Object.assign(this.camera,{yaw:0.55,pitch:-0.25,distance:3.7});this.draw();}
 zoom(factor){this.camera.distance=Math.max(1.5,Math.min(25,this.camera.distance*factor));this.draw();}
 showIssues(value){this.camera.issues=value;this.draw();}
}
