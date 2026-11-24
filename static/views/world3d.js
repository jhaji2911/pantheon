/* world3d — Pantheon: the world the CIs live in.
 *
 * A third-person world you walk through, but the people in it are not props: each CI has
 * a body, a home, and a habit. They walk to work at dawn, gather at the Agora at dusk,
 * rest at night — their positions come from the Pantheon simulation (a real, persistent
 * world clock), so they live whether or not you are looking. Walk up to one and press E
 * to talk, M to step into its mind. Every place opens an in-world screen, and the MIST
 * core at the centre is the god's seat: walk up to it and press E to see and govern.
 *
 * The brain (`minds`, see minds.py) is off by default. Press B to turn it on: each CI then
 * perceives what is near it, decides with a metered model call, and acts — walking, working,
 * approaching and speaking to others within earshot. Every decision is logged in its mind (M).
 */
import * as THREE from "three";
import { Sky } from "/api/static/vendor/Sky.js";
import { EffectComposer } from "/api/static/vendor/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "/api/static/vendor/jsm/postprocessing/RenderPass.js";
import { GTAOPass } from "/api/static/vendor/jsm/postprocessing/GTAOPass.js";
import { UnrealBloomPass } from "/api/static/vendor/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "/api/static/vendor/jsm/postprocessing/OutputPass.js";
import * as GPU from "./gpu.js";
import { buildCity, carModel, mergeStatic } from "./city.js";
import { esc, num, f2, colonyData, loadColony, getJSON, postJSON,
         paint, chip, panel, table, empty, note, errbox } from "../app.js";
import { DOMAIN_HUE, TIER, presence } from "../being.js";
import * as colonyView from "./colony.js";
import * as worldView from "./world.js";
import * as intercomView from "./intercom.js";
import * as assemblyView from "./assembly.js";
import * as ciView from "./ci.js";
import * as mistView from "./mist.js";
import * as builderView from "./builder.js";
import { startVoiceCapture, sendVoiceTurn, audioURLFromResponse } from "../voice.js";

const hue01 = h => (h % 360) / 360;
const colorOf = h => new THREE.Color().setHSL(hue01(h), 0.65, 0.55);

let renderer = null, scene = null, camera = null;
let raf = 0, clock = new THREE.Clock();
let avatar = null, avBody = null;
let beings = new Map();          // name -> {group, agent, p}
let interactables = [];          // {obj, kind, label, params, mind}
let rootEl = null;
let hud = {};                    // {prompt, zone, crosshair, compass, controls, brain}
let keys = {};
let theta = 0, phi = 0.5, radius = 9;
let cameraReady = false;
let dragging = false, lastX = 0, lastY = 0, movedOnDrag = 0;
let overlay = null;
let near = null;
let disposed = false;

let pantheon = null;             // latest /api/pantheon
let pBuildings = new Map();      // place id -> group
let worldAssets = new Map();      // asset id -> rendered group
let workstations = new Map();    // CI name -> personal physical workstation
let sunLight = null, hemi = null, stars = null, moonMesh = null, sky = null;
let envGen = null, envRT = null, envSky = null, envScene = null, envSunKey = "";
let lamps = [], windowMats = [];   // night lighting: street lamps and lit interiors
let layout = null, colliders = [];
let city = null, cityKey = "";   // the rendered town plan (city.js), rebuilt when the plan changes
let lampPool = [], lampPoolAt = 0;  // a few real lights that follow the street lamps nearest the visitor
let darkness = 0;                // 0 day … 1 night, from applyDayNight
let composer = null, gtaoPass = null, bloomPass = null, quality = "high";
let G = null, gpuPipe = null, atmos = null;   // WebGPU: library handle, TSL post pipeline, compute atmosphere (gpu.js)
const skySet = (s, k, v) => G ? GPU.setSky(s, k, v)
  : (v && v.isVector3 ? s.material.uniforms[k].value.copy(v) : (s.material.uniforms[k].value = v));
const skyGet = (s, k) => G ? GPU.getSky(s, k) : s.material.uniforms[k].value;
let lastThought = new Map();     // resident → last thought shown in a bubble
let serverOffset = 0;            // server clock − client clock, seconds
let hourOverride = null;         // test hook (__w3d.hour) for inspecting lighting at any time of day
let talkBubbles = [];            // {sprite, until, key}
let faceBubbles = [];            // DOM speech balloons anchored above CI bodies
let faceVoice = {name:null, capture:null, busy:false, abort:null};

const AVATAR_SPEED = 6.5;
const REACH = 4.2;
const WORLD_R = 108;
const PLAYER_START = {x:6, z:9};

const PLACE_FALLBACK = {
  agora:        {name:"The Agora",        x:0,    z:0,    hue:210},
  foundry:      {name:"The Foundry",      x:16,   z:10,   hue:142},
  observatory:  {name:"The Observatory",  x:-16,  z:10,   hue:42},
  conservatory: {name:"The Conservatory", x:-16,  z:-10,  hue:176},
  lattice:      {name:"The Lattice",      x:16,   z:-10,  hue:262},
  study:        {name:"The Study",        x:0,    z:13,   hue:320},
  hall:         {name:"The Hall",         x:0,    z:-13,  hue:48},
  archive:      {name:"The Archive",      x:22,   z:0,    hue:200},
};

/* place -> [screen kind, prompt label, screen param] */
const PLACE_ROLE = {
  hall:          ["assemble", "call the assembly"],
  archive:       ["colony",   "open the ledger"],
  agora:         ["machine",  "behold MIST · the machine"],
  foundry:       ["work", "the Foundry · cyber",        "cyber"],
  observatory:   ["work", "the Observatory · orbital",  "orbital"],
  conservatory:  ["work", "the Conservatory · climate", "climate"],
  lattice:       ["work", "the Lattice · quantum",      "quantum"],
  study:         ["work", "the Study · world",          "world"],
};

/* ---------------------------------------------------------------- 3D helpers */
function makeLabel(text, color, width){
  const canvas = document.createElement("canvas");
  canvas.width = 1024; canvas.height = 224;
  const g = canvas.getContext("2d");
  let size = 96;   // shrink long names to fit rather than clip them
  do { g.font = `700 ${size}px ui-monospace, Menlo, Consolas, monospace`; size -= 6; }
  while (size > 30 && g.measureText(text).width > 980);
  g.textAlign = "center"; g.textBaseline = "middle";
  g.fillStyle = color;
  g.fillText(text, 512, 120);
  const tex = new THREE.CanvasTexture(canvas);
  tex.minFilter = THREE.LinearFilter;
  const mat = new THREE.SpriteMaterial({map: tex, transparent: true, depthWrite: false});
  const s = new THREE.Sprite(mat);
  s.scale.set(width, width * 0.22, 1);
  return s;
}

function stdMat(color, opt){
  return new THREE.MeshStandardMaterial(Object.assign(
    {color, roughness: 0.6, metalness: 0.2}, opt || {}));
}

function buildBeing(a){
  // Human-scale, grounded office attire. Domain colour is a small ID detail, not
  // a glowing body; rank is conveyed by a discreet lapel pin rather than orbiting rings.
  const hue = DOMAIN_HUE[a.domain] != null ? DOMAIN_HUE[a.domain] : 210;
  const lvl = (TIER[a.tier] || TIER.worker).level;
  const g = new THREE.Group();
  const h = 1.72 + lvl * 0.035;
  const jacketColors = [0x34404a, 0x303a45, 0x293743, 0x3c3c43, 0x35433f, 0x44403a];
  const pick = Array.from(a.name || "CI").reduce((n, c) => n + c.charCodeAt(0), 0) % jacketColors.length;
  const cloth = new THREE.MeshStandardMaterial({color: jacketColors[pick], roughness: 0.88});
  const shirt = new THREE.MeshStandardMaterial({color: 0xb6b4aa, roughness: 0.92});
  const skin = new THREE.MeshStandardMaterial({color: 0x9b735f, roughness: 0.82});
  const hair = new THREE.MeshStandardMaterial({color: 0x292522, roughness: 0.94});
  const trousers = new THREE.MeshStandardMaterial({color: 0x252a30, roughness: 0.9});
  const shoes = new THREE.MeshStandardMaterial({color: 0x17191b, roughness: 0.82});
  const accent = new THREE.MeshStandardMaterial({color: colorOf(hue), roughness: 0.65, metalness: 0.12});
  const capsule = (rt, rb, len, mat, radial=10) => new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, len, radial), mat);

  // pelvis + tailored jacket, collar and shirt front
  const pelvis = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.25, 0.22), trousers);
  pelvis.position.y = 0.94; g.add(pelvis);
  const torso = new THREE.Mesh(new THREE.BoxGeometry(0.47, 0.60, 0.27), cloth);
  torso.position.y = 1.30; g.add(torso);
  const shirtFront = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.42, 0.018), shirt);
  shirtFront.position.set(0, 1.31, 0.145); g.add(shirtFront);
  const collar = new THREE.Mesh(new THREE.ConeGeometry(0.095, 0.16, 4), shirt);
  collar.position.set(0, 1.58, 0.12); collar.rotation.x = Math.PI; g.add(collar);

  // articulated shoulders, upper/lower arms, hands
  const arms = [], legs = [];
  for (const side of [-1, 1]){
    const shoulder = new THREE.Mesh(new THREE.SphereGeometry(0.115, 12, 10), cloth);
    shoulder.position.set(side * 0.29, 1.51, 0); g.add(shoulder);
    const upper = capsule(0.083, 0.09, 0.30, cloth, 9);
    upper.position.set(side * 0.32, 1.33, 0); g.add(upper);
    const elbow = new THREE.Mesh(new THREE.SphereGeometry(0.073, 10, 8), cloth);
    elbow.position.set(side * 0.32, 1.16, 0); g.add(elbow);
    const lower = capsule(0.064, 0.073, 0.27, cloth, 9);
    lower.position.set(side * 0.32, 0.99, 0); g.add(lower);
    const hand = new THREE.Mesh(new THREE.SphereGeometry(0.065, 10, 8), skin);
    hand.position.set(side * 0.32, 0.82, 0.015); g.add(hand);
    arms.push({shoulder, upper, elbow, lower, hand, side});

    const thigh = capsule(0.105, 0.09, 0.38, trousers, 10);
    thigh.position.set(side * 0.115, 0.70, 0); g.add(thigh);
    const knee = new THREE.Mesh(new THREE.SphereGeometry(0.085, 10, 8), trousers);
    knee.position.set(side * 0.115, 0.50, 0); g.add(knee);
    const shin = capsule(0.065, 0.08, 0.36, trousers, 9);
    shin.position.set(side * 0.115, 0.30, 0); g.add(shin);
    const foot = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.09, 0.25), shoes);
    foot.position.set(side * 0.115, 0.09, 0.045); g.add(foot);
    legs.push({thigh, knee, shin, foot, side});
  }

  // neck, head, ears, hairline, brows and eyes (neutral human features)
  const neck = capsule(0.075, 0.08, 0.13, skin, 10); neck.position.y = 1.68; g.add(neck);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.135, 20, 16), skin);
  head.scale.set(0.86, 1.18, 0.92); head.position.set(0, 1.84, 0.018); g.add(head);
  const hairCap = new THREE.Mesh(new THREE.SphereGeometry(0.14, 18, 12, 0, Math.PI*2, 0, Math.PI*0.48), hair);
  hairCap.scale.set(0.9, 0.78, 0.95); hairCap.position.set(0, 1.91, -0.005); g.add(hairCap);
  const eyeMat = new THREE.MeshStandardMaterial({color: 0x252322, roughness: 0.6});
  const faceParts=[hairCap];
  for (const side of [-1, 1]){
    const ear = new THREE.Mesh(new THREE.SphereGeometry(0.025, 8, 8), skin);
    ear.position.set(side * 0.117, 1.84, 0.005); g.add(ear);faceParts.push(ear);
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.012, 8, 8), eyeMat);
    eye.position.set(side * 0.043, 1.855, 0.135); g.add(eye);faceParts.push(eye);
    const brow = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.009, 0.012), hair);
    brow.position.set(side * 0.043, 1.88, 0.13); g.add(brow);faceParts.push(brow);
  }

  // subtle pin: a small, stable domain marker on the left lapel
  const pin = new THREE.Mesh(new THREE.SphereGeometry(0.025, 8, 8), accent);
  pin.position.set(-0.15, 1.48, 0.15); g.add(pin);
  const label = makeLabel(a.name, "#e5e1d8", 2.8);
  label.position.y = h + 0.20; g.add(label);
  const poseObjects=[pelvis,torso,shirtFront,collar,neck,head,pin,...faceParts,
    ...arms.flatMap(x=>[x.shoulder,x.upper,x.elbow,x.lower,x.hand]),
    ...legs.flatMap(x=>[x.thigh,x.knee,x.shin,x.foot])];
  const standingPose=poseObjects.map(obj=>({obj,position:obj.position.clone(),rotation:obj.rotation.clone()}));
  g.userData = {agent: a, pelvis, neck, head, torso, arms, legs, faceParts, label, hue, height: h,
    standingPose, seated:false, armsSwing: 0, legsSwing: 0};
  return g;
}

function setBeingSeated(group,seated){
  const u=group.userData||{};
  if(u.seated===seated)return;
  u.seated=seated;
  if(!seated){
    for(const item of u.standingPose||[]){item.obj.position.copy(item.position);item.obj.rotation.copy(item.rotation);}
    return;
  }
  u.pelvis.position.set(0,0.68,0);
  u.torso.position.set(0,1.08,0);
  u.neck.position.set(0,1.43,0);
  u.head.position.set(0,1.61,0.018);
  for(const part of u.faceParts||[])part.position.y-=0.16;
  for(const arm of u.arms||[]){
    arm.shoulder.position.y=1.34;arm.upper.position.y=1.18;arm.elbow.position.y=1.02;
    arm.lower.position.y=0.89;arm.hand.position.y=0.77;
  }
  for(const leg of u.legs||[]){
    leg.thigh.position.set(leg.side*0.115,0.70,0.13);leg.thigh.rotation.x=Math.PI/2;
    leg.knee.position.set(leg.side*0.115,0.68,0.36);
    leg.shin.position.set(leg.side*0.115,0.43,0.36);
    leg.foot.position.set(leg.side*0.115,0.09,0.52);
  }
}

/* ---------------------------------------------------------------- the world */
function colonyAgents(){ const c = colonyData(); return (c && Array.isArray(c.agents)) ? c.agents : []; }

function placesList(){
  if (pantheon && Array.isArray(pantheon.places) && pantheon.places.length) return pantheon.places;
  return Object.entries(PLACE_FALLBACK).map(([id, p]) => Object.assign({id}, p));
}

async function loadPantheon(){
  try {
    const r = await getJSON("/api/pantheon", {timeout: 10000});
    const d = r && r.ok ? r.data : null;
    if (d && Array.isArray(d.agents)){
      pantheon = d;
      if (d.clock && d.clock.now) serverOffset = d.clock.now - Date.now() / 1000;
      if (scene){ applyLayout(d.layout); syncAgents(); syncDynamicPlaces(); syncWorldAssets(); shadowify(scene); }
    }
  } catch (e) { /* the world is unreachable; keep the last good state */ }
}

async function toggleMinds(){
  const want = !(pantheon && pantheon.minds);
  try { await postJSON("/api/pantheon/minds", {on: want}, {timeout: 15000}); }
  catch (e) { /* keep the last state */ }
  loadPantheon();
}

/* ---------------------------------------------------------------- scenery */
/* Procedural surface textures: low-contrast value noise so large planes read as material,
 * not flat colour. Generated once on a canvas; no image downloads. */
function noiseTexture(base, spread, grain, repeat){
  const size=256, c=document.createElement("canvas"); c.width=c.height=size;
  const g=c.getContext("2d"), img=g.createImageData(size,size);
  const [r0,g0,b0]=base;
  let seed=1337;
  const rnd=()=>((seed=(seed*16807)%2147483647)/2147483647);
  const coarse=[];for(let i=0;i<17*17;i++)coarse.push(rnd());
  const lerp=(a,b,t)=>a+(b-a)*t;
  for(let y=0;y<size;y++)for(let x=0;x<size;x++){
    const fx=x/16,fy=y/16,ix=Math.floor(fx)%16,iy=Math.floor(fy)%16,tx=fx-Math.floor(fx),ty=fy-Math.floor(fy);
    const v=lerp(lerp(coarse[iy*17+ix],coarse[iy*17+ix+1],tx),lerp(coarse[(iy+1)*17+ix],coarse[(iy+1)*17+ix+1],tx),ty);
    const n=(v-0.5)*spread+(rnd()-0.5)*grain;
    const k=(y*size+x)*4;
    img.data[k]=Math.max(0,Math.min(255,r0+n));img.data[k+1]=Math.max(0,Math.min(255,g0+n*1.05));
    img.data[k+2]=Math.max(0,Math.min(255,b0+n*0.85));img.data[k+3]=255;
  }
  g.putImageData(img,0,0);
  const tex=new THREE.CanvasTexture(c);
  tex.wrapS=tex.wrapT=THREE.RepeatWrapping;tex.repeat.set(repeat,repeat);
  tex.colorSpace=THREE.SRGBColorSpace;tex.anisotropy=8;
  return tex;
}

function shadowify(root){
  root.traverse(o=>{
    if(!o.isMesh)return;
    const m=o.material;
    if(!m||m.isShaderMaterial||m.isMeshBasicMaterial){o.castShadow=o.receiveShadow=false;return;}  // sky, screens, moon
    o.castShadow=!m.transparent;o.receiveShadow=true;
  });
}

function applyLayout(lay){
  if(!lay)return;
  layout=lay;colliders=lay.colliders||[];
  // Rebuild the rendered town only when the plan itself changed (new house, asset or road).
  const key=[(lay.houses||[]).map(h=>h.id+h.x).join(),(lay.sited||[]).length,(lay.roads||[]).length,(lay.lamps||[]).length].join("|");
  if(key===cityKey)return;
  cityKey=key;
  if(city){scene.remove(city.group);city.dispose();}
  city=buildCity(lay);scene.add(city.group);
  interactables=interactables.filter(it=>it.kind!=="house");
  for(const h of lay.houses||[]){
    const marker=new THREE.Object3D();marker.position.set(h.x,0,h.z);marker.userData={placeId:h.id};
    interactables.push({obj:marker,kind:"house",label:"visit "+h.name,params:[h.owner]});
  }
}

/* A handful of real point lights, reassigned to the street lamps nearest the visitor; every
 * other lamp still glows (emissive + bloom). Dozens of live lights would cost every frame. */
function updateLampPool(now){
  if(!city||!avatar)return;
  if(!lampPool.length){
    for(let i=0;i<8;i++){const l=new THREE.PointLight(0xffd9a0,0,18,2);scene.add(l);lampPool.push(l);}
  }
  if(now-lampPoolAt>400){
    lampPoolAt=now;
    const at=avatar.position;
    const nearest=city.lampPositions.slice().sort((a,b)=>a.distanceToSquared(at)-b.distanceToSquared(at));
    lampPool.forEach((l,i)=>{if(nearest[i])l.position.copy(nearest[i]);});
  }
  for(const l of lampPool)l.intensity=26*darkness;
}

function buildHallTable(){
  const hall=placesList().find(p=>p.id==="hall")||PLACE_FALLBACK.hall;
  const tableGroup=new THREE.Group();
  const wood=new THREE.MeshStandardMaterial({color:0x594c3d,roughness:0.78});
  const metal=new THREE.MeshStandardMaterial({color:0x3b4244,metalness:0.5,roughness:0.55});
  const top=new THREE.Mesh(new THREE.CylinderGeometry(1.28,1.28,0.16,32),wood);top.position.y=0.84;tableGroup.add(top);
  const base=new THREE.Mesh(new THREE.CylinderGeometry(0.24,0.38,0.72,12),metal);base.position.y=0.43;tableGroup.add(base);
  tableGroup.position.set(hall.x,0,hall.z);scene.add(tableGroup);
  for(let i=0;i<6;i++){
    const a=(Math.PI*2*i/6)-Math.PI/2,seat=new THREE.Group();
    const seatTop=new THREE.Mesh(new THREE.BoxGeometry(0.78,0.13,0.72),wood);seatTop.position.y=0.5;seat.add(seatTop);
    const back=new THREE.Mesh(new THREE.BoxGeometry(0.78,0.82,0.12),wood);back.position.set(0,0.94,-0.31);seat.add(back);
    for(const sx of [-0.28,0.28])for(const sz of [-0.22,0.22]){
      const leg=new THREE.Mesh(new THREE.BoxGeometry(0.07,0.46,0.07),metal);leg.position.set(sx,0.24,sz);seat.add(leg);
    }
    seat.position.set(hall.x+Math.cos(a)*2.25,0,hall.z+Math.sin(a)*2.25);
    seat.rotation.y=a+Math.PI/2;scene.add(seat);
  }
}

function workstationHome(agent){
  const body=pantheon&&pantheon.agents&&pantheon.agents.find(p=>p.name.toLowerCase()===agent.name.toLowerCase());
  if(body&&body.home)return body.home;
  const homes={cyber:"foundry",orbital:"observatory",climate:"conservatory",quantum:"lattice",world:"study",brief:"study"};
  return homes[agent.domain]||"study";
}

function stationArtifact(name){
  return ((pantheon&&pantheon.artifacts)||[]).find(a=>a.kind==="workboard"&&String(a.owner||"").toLowerCase()===String(name||"").toLowerCase())||null;
}

function drawWorkstation(station,agent,artifact){
  const c=station.canvas.getContext("2d"),w=station.canvas.width,h=station.canvas.height;
  const a=agent||{};const task=a.doing;const affect=a.affect||{};const work=task?`T${task.task_id} · ${task.domain}`:"no active task";
  const content=artifact&&artifact.content||{};
  const tool=(content.tools||[])[0];
  let result=tool?tool.result:"no instrument result recorded";
  try{const parsed=typeof result==="string"?JSON.parse(result):result;result=parsed&&parsed.value!==undefined?String(parsed.value):JSON.stringify(parsed);}catch(e){}
  c.fillStyle="#08121a";c.fillRect(0,0,w,h);
  c.fillStyle="#6ce0c4";c.font="bold 24px ui-monospace,Menlo,monospace";c.fillText((a.name||station.name)+" / WORKSPACE",18,34);
  c.fillStyle="#dbe6ef";c.font="18px ui-monospace,Menlo,monospace";c.fillText((a.status||"active").toUpperCase()+" · "+(a.tier||"CI")+" · "+(a.domain||"world"),18,70);
  c.fillStyle="#f2b04a";c.fillText(work.slice(0,42),18,108);
  c.fillStyle="#a9bac7";c.font="15px ui-monospace,Menlo,monospace";
  const question=task&&task.question?String(task.question):"waiting for assigned work";
  c.fillText(question.slice(0,50),18,142);c.fillText(question.length>50?question.slice(50,100):"",18,164);
  c.fillStyle="#a98bdb";c.fillText("observed affect · "+(affect.label||"settling in"),18,202);
  c.fillStyle="#8298ab";c.fillText("model · "+((a.last_call&&a.last_call.model)||"not recorded")+" · verified "+(a.tasks_verified||0),18,232);
  c.fillStyle="#6ce0c4";c.fillText("saved artifact · "+(artifact?artifact.title:"workboard pending"),18,262);
  c.fillStyle="#d0c7a5";c.fillText("latest instrument · "+(tool?tool.name:"none recorded")+" → "+String(result).slice(0,46),18,292);
  station.texture.needsUpdate=true;
}

function deskFor(name){
  return ((layout&&layout.workstations)||[]).find(w=>w.name.toLowerCase()===String(name).toLowerCase())||null;
}

/* A resident's own machine at its desk inside its workplace (positions from the town plan):
 * desk, two monitors (the left one shows its live workboard), a tower, keyboard and chair. */
function makeWorkstation(agent,homeId){
  const group=new THREE.Group(),wood=new THREE.MeshStandardMaterial({color:0x514637,roughness:0.82});
  const metal=new THREE.MeshStandardMaterial({color:0x394144,metalness:0.52,roughness:0.48});
  const top=new THREE.Mesh(new THREE.BoxGeometry(1.38,0.12,0.74),wood);top.position.y=0.82;group.add(top);
  for(const sx of [-0.55,0.55])for(const sz of [-0.26,0.26]){
    const leg=new THREE.Mesh(new THREE.BoxGeometry(0.07,0.78,0.07),metal);leg.position.set(sx,0.4,sz);group.add(leg);
  }
  const monitor=new THREE.Mesh(new THREE.BoxGeometry(0.9,0.62,0.09),metal);monitor.position.set(0,1.25,-0.14);group.add(monitor);
  const stand=new THREE.Mesh(new THREE.CylinderGeometry(0.03,0.09,0.36,10),metal);stand.position.set(0,0.98,-0.16);group.add(stand);
  const side=new THREE.Mesh(new THREE.BoxGeometry(0.62,0.4,0.06),metal);side.position.set(0.66,1.14,-0.06);side.rotation.y=-0.45;group.add(side);
  const sideGlow=new THREE.MeshStandardMaterial({color:0x10262c,emissive:0x2c8f80,emissiveIntensity:0.6});
  const sideScreen=new THREE.Mesh(new THREE.PlaneGeometry(0.56,0.34),sideGlow);sideScreen.position.set(0.65,1.14,-0.025);sideScreen.rotation.y=-0.45;group.add(sideScreen);
  const tower=new THREE.Mesh(new THREE.BoxGeometry(0.22,0.46,0.48),metal);tower.position.set(-0.52,1.11,-0.05);group.add(tower);
  const led=new THREE.Mesh(new THREE.BoxGeometry(0.01,0.02,0.02),new THREE.MeshStandardMaterial({color:0x6ce0c4,emissive:0x6ce0c4,emissiveIntensity:2}));led.position.set(-0.41,1.28,0.19);group.add(led);
  const canvas=document.createElement("canvas");canvas.width=512;canvas.height=320;
  const texture=new THREE.CanvasTexture(canvas);texture.minFilter=THREE.LinearFilter;
  const screen=new THREE.Mesh(new THREE.PlaneGeometry(0.8,0.5),new THREE.MeshBasicMaterial({map:texture,side:THREE.DoubleSide}));
  screen.position.set(0,1.26,-0.087);group.add(screen);
  const keyboard=new THREE.Mesh(new THREE.BoxGeometry(0.58,0.045,0.2),metal);keyboard.position.set(0,0.91,0.2);group.add(keyboard);
  const chair=new THREE.Group(),chairMat=new THREE.MeshStandardMaterial({color:0x343b3d,roughness:0.8});
  const cushion=new THREE.Mesh(new THREE.BoxGeometry(0.62,0.13,0.62),chairMat);cushion.position.y=0.52;chair.add(cushion);
  const chairBack=new THREE.Mesh(new THREE.BoxGeometry(0.62,0.72,0.1),chairMat);chairBack.position.set(0,0.88,-0.26);chair.add(chairBack);
  chair.position.set(0,0,1.05);group.add(chair);
  const label=makeLabel(agent.name,"#e5e1d8",2.1);label.position.set(0,2.1,0);group.add(label);
  const desk=deskFor(agent.name);
  if(desk)group.position.set(desk.x,0,desk.z);
  group.userData={ciName:agent.name,homeId,canvas,texture,label};
  scene.add(group);
  const entry={name:agent.name,group,texture,canvas,homeId};
  drawWorkstation(entry,agent,stationArtifact(agent.name));
  interactables.push({obj:group,kind:"computer",mind:agent.name,label:"open "+agent.name+"’s workstation",params:[agent.name]});
  return entry;
}

function syncWorkstations(){
  if(!scene||!pBuildings.size||!layout)return;
  const agents=colonyAgents().filter(a=>a.name&&a.status!=="retired");
  const valid=new Set(agents.map(a=>a.name.toLowerCase()));
  for(const [key,station] of workstations){
    if(!valid.has(key)){scene.remove(station.group);station.texture.dispose();workstations.delete(key);}
  }
  interactables=interactables.filter(it=>it.kind!=="computer"||valid.has(String(it.mind||"").toLowerCase()));
  const byHome={};
  agents.forEach(a=>{const home=workstationHome(a);(byHome[home]||(byHome[home]=[])).push(a);});
  for(const [home,rows] of Object.entries(byHome))rows.sort((a,b)=>a.name.localeCompare(b.name));
  for(const [home,rows] of Object.entries(byHome))rows.forEach((agent,index)=>{
    const key=agent.name.toLowerCase();let station=workstations.get(key);
    if(!station||station.homeId!==home){
      if(station){scene.remove(station.group);station.texture.dispose();}
      station=makeWorkstation(agent,home);workstations.set(key,station);
    }
    const desk=deskFor(agent.name);
    if(desk)station.group.position.set(desk.x,0,desk.z);
    drawWorkstation(station,agent,stationArtifact(agent.name));
  });
}

function buildSocialPavilion(p){
  const group=new THREE.Group(),hue=p.hue||210;
  const stone=new THREE.MeshStandardMaterial({color:0x77736b,roughness:0.9});
  const timber=new THREE.MeshStandardMaterial({color:0x594c3d,roughness:0.82});
  const metal=new THREE.MeshStandardMaterial({color:colorOf(hue),metalness:0.28,roughness:0.55});
  const base=new THREE.Mesh(new THREE.CylinderGeometry(3.4,3.55,0.18,32),stone);base.position.y=0.09;group.add(base);
  const table=new THREE.Mesh(new THREE.CylinderGeometry(1.1,1.1,0.13,24),timber);table.position.y=0.82;group.add(table);
  const stem=new THREE.Mesh(new THREE.CylinderGeometry(0.16,0.24,0.68,12),metal);stem.position.y=0.43;group.add(stem);
  for(let i=0;i<6;i++){
    const a=i*Math.PI/3;
    const post=new THREE.Mesh(new THREE.CylinderGeometry(0.09,0.12,3.05,8),timber);
    post.position.set(Math.cos(a)*2.85,1.62,Math.sin(a)*2.85);group.add(post);
    const seat=new THREE.Mesh(new THREE.BoxGeometry(0.86,0.12,0.48),timber);
    seat.position.set(Math.cos(a)*1.9,0.48,Math.sin(a)*1.9);seat.rotation.y=-a;group.add(seat);
  }
  const roof=new THREE.Mesh(new THREE.CylinderGeometry(3.15,3.45,0.18,6),metal);
  roof.position.y=3.22;roof.rotation.y=Math.PI/6;group.add(roof);
  const label=makeLabel(p.name,"#e5e1d8",5.0);label.position.set(0,4.08,0);group.add(label);
  const subtitle=makeLabel((p.interactions||0)+" saved meetings","#d9c99e",2.8);subtitle.position.set(0,3.72,0);group.add(subtitle);
  group.position.set(p.x,0,p.z);
  group.userData={label,labelY:4.08,hue,placeId:p.id,width:7,depth:7,buildingH:3.4,dynamic:true};
  scene.add(group);pBuildings.set(p.id,group);
  return group;
}

function syncDynamicPlaces(){
  if(!scene)return;
  for(const p of placesList()){
    if(p.kind!=="social"&&!p.dynamic)continue;
    let group=pBuildings.get(p.id);
    if(!group)group=buildSocialPavilion(p);
    const exists=interactables.some(it=>it.obj===group);
    if(!exists)interactables.push({obj:group,kind:"assemble",label:"enter "+p.name,params:[]});
  }
}

/* Generated assets, drawn by kind (and, for street furniture, by what the name says it is).
 * The lot was chosen by the town plan; local +z faces the street. */
function buildWorldAsset(a){
  const g=new THREE.Group();
  const color=new THREE.Color(a.color||"#78858a");
  const mat=new THREE.MeshStandardMaterial({color,roughness:0.78,metalness:0.12});
  const trim=new THREE.MeshStandardMaterial({color:0x30373a,roughness:0.72,metalness:0.28});
  const iron=new THREE.MeshStandardMaterial({color:0x2c3133,metalness:0.7,roughness:0.4});
  const glassLit=new THREE.MeshStandardMaterial({color:0x34444a,roughness:0.06,metalness:0.3,emissive:0xffc985,emissiveIntensity:0});
  windowMats.push(glassLit);
  const w=Number(a.width)||4,d=Number(a.depth)||4,h=Number(a.height)||3;
  const box=(W,H,D,m,x,y,z)=>{const o=new THREE.Mesh(new THREE.BoxGeometry(W,H,D),m);o.position.set(x,y,z);g.add(o);return o;};
  const name=String(a.name||"").toLowerCase();
  if(a.kind==="car"){
    const car=carModel(color.getHex());car.scale.set(d/4.5,h/1.45,w/1.84);car.rotation.y=Math.PI/2;g.add(car);
  }else if(a.kind==="building"){
    const floors=Math.max(1,Math.round(h/3.2)),fh=h/floors;
    box(w,h,d,mat,0,h/2,0);
    box(w+0.3,0.5,d+0.3,trim,0,h+0.25,0);                                   // parapet
    box(w*0.3,0.9,d*0.3,trim,w*0.18,h+0.95,-d*0.15);                        // rooftop plant
    const cols=Math.max(2,Math.floor(w/2.2));
    for(let f=0;f<floors;f++)for(let c=0;c<cols;c++){
      const x=-w/2+(c+0.5)*w/cols,y=f*fh+fh*0.55;
      if(f===0&&Math.abs(x)<1.2)continue;                                  // the entrance bay
      box(w/cols*0.6,fh*0.48,0.08,glassLit,x,y,d/2+0.02);
      box(w/cols*0.6,fh*0.48,0.08,glassLit,x,y,-d/2-0.02);
    }
    box(1.8,2.4,0.1,new THREE.MeshStandardMaterial({color:0x22292b,roughness:0.2,metalness:0.5}),0,1.2,d/2+0.04);
    box(3.2,0.14,1.4,trim,0,2.7,d/2+0.7);                                   // entrance canopy
  }else if(a.kind==="bridge"){
    box(w,0.35,d,mat,0,h*0.55,0);
    for(const x of [-w*0.38,w*0.38])box(0.35,h,d*0.85,trim,x,h*0.32,0);
    box(w,0.15,0.12,trim,0,h*0.88,d*0.42);
  }else if(a.kind==="park"){
    const lawn=new THREE.Mesh(new THREE.PlaneGeometry(w,d),new THREE.MeshStandardMaterial({color:0x5c7a45,roughness:1}));
    lawn.rotation.x=-Math.PI/2;lawn.position.y=0.03;g.add(lawn);
    const gravel=new THREE.MeshStandardMaterial({color:0xb4a98f,roughness:1});
    const path=new THREE.Mesh(new THREE.RingGeometry(Math.min(w,d)*0.28,Math.min(w,d)*0.34,40),gravel);
    path.rotation.x=-Math.PI/2;path.position.y=0.04;g.add(path);
    for(const [x,z] of [[-w*.32,-d*.3],[w*.3,-d*.28],[-w*.28,d*.3],[w*.33,d*.27]]){
      box(0.24,1.6,0.24,new THREE.MeshStandardMaterial({color:0x51463a,roughness:1}),x,0.8,z);
      const crown=new THREE.Mesh(new THREE.IcosahedronGeometry(1.3,1),new THREE.MeshStandardMaterial({color:0x3f5937,roughness:1,flatShading:true}));
      crown.position.set(x,2.4,z);g.add(crown);
    }
    box(1.6,0.6,0.8,mat,0,0.3,0);                                            // play structure
  }else if(a.kind==="sculpture"){
    box(w*.5,.45,d*.5,trim,0,.23,0);
    const form=new THREE.Mesh(new THREE.TorusKnotGeometry(Math.min(w,d)*.19,Math.min(w,d)*.055,96,12),
      new THREE.MeshStandardMaterial({color,metalness:0.85,roughness:0.25}));
    form.position.y=h*.53;g.add(form);
  }else if(/kiosk|terminal|station/.test(name)){
    box(w,h*0.95,d,mat,0,h*0.475,0);
    box(w*0.8,h*0.42,0.05,new THREE.MeshStandardMaterial({color:0x0e2026,emissive:0x2c8f80,emissiveIntensity:0.7}),0,h*0.62,d/2+0.03);
    box(w+0.2,0.1,d+0.2,trim,0,h*0.98,0);
  }else if(/post|mast|clock|beacon/.test(name)){
    box(0.16,h,0.16,iron,0,h/2,0);
    box(Math.min(0.9,w),0.5,Math.min(0.5,d),mat,0,h-0.3,0);
    const led=box(0.08,0.08,0.08,new THREE.MeshStandardMaterial({color:0xff6a3a,emissive:0xff6a3a,emissiveIntensity:2}),0,h+0.06,0);
    led.castShadow=false;
  }else{
    // bench: slatted seat and back on cast-iron ends
    const wood=new THREE.MeshStandardMaterial({color:0x6d5039,roughness:0.75});
    for(let i=0;i<4;i++)box(w,0.05,0.11,wood,0,0.46,-0.18+i*0.12);
    for(let i=0;i<3;i++)box(w,0.1,0.04,wood,0,0.62+i*0.13,-0.27).rotation.x=-0.18;
    for(const x of [-w/2+0.12,w/2-0.12]){box(0.07,0.46,0.5,iron,x,0.23,0);box(0.07,0.5,0.06,iron,x,0.72,-0.28);}
  }
  g.traverse(o=>{if(o.isMesh&&!o.material.transparent){o.castShadow=true;o.receiveShadow=true;}});
  mergeStatic(g);
  const label=makeLabel(a.name,"#e5e1d8",Math.max(2.8,Math.min(6,w*1.2)));
  label.position.set(0,h+0.7,0);g.add(label);
  label.visible=["building","park","sculpture","bridge"].includes(a.kind);   // benches name themselves on approach
  const site=((layout&&layout.sited)||[]).find(s=>String(s.id)===String(a.id));
  g.position.set(site?site.x:Number(a.x)||0,0,site?site.z:Number(a.z)||0);
  if(site)g.rotation.y=site.yaw||0;
  g.userData={label,labelY:h+0.7,hue:210,assetId:a.id,owner:a.owner,kind:a.kind,width:w,depth:d,buildingH:h,dynamic:true};
  scene.add(g);
  interactables.push({obj:g,kind:"builder",label:"inspect "+a.name,params:[]});
  return g;
}

function syncWorldAssets(){
  if(!scene)return;
  const assets=(pantheon&&Array.isArray(pantheon.assets))?pantheon.assets:[];
  const valid=new Set(assets.map(a=>String(a.id)));
  for(const [id,group] of worldAssets){
    if(!valid.has(id)){scene.remove(group);worldAssets.delete(id);interactables=interactables.filter(it=>it.obj!==group);}
  }
  for(const asset of assets){
    const id=String(asset.id);
    if(!worldAssets.has(id))worldAssets.set(id,buildWorldAsset(asset));
    const site=((layout&&layout.sited)||[]).find(s=>String(s.id)===id),g=worldAssets.get(id);
    if(site&&g){g.position.set(site.x,0,site.z);g.rotation.y=site.yaw||0;}
  }
}

function buildBuildings(){
  pBuildings.clear();
  for (const p of placesList()){
    if(p.kind==="social"||p.dynamic){buildSocialPavilion(p);continue;}
    const hue = p.hue != null ? p.hue : 210;
    const facadeColors = [0x77736b,0x626b6d,0x8a8172,0x6c7068,0x777a78];
    const seed = Array.from(p.id || "x").reduce((n,c)=>n+c.charCodeAt(0),0);
    const facade = facadeColors[seed % facadeColors.length];
    const g = new THREE.Group();
    const width = p.id === "agora" ? 9 : 7.4;
    const depth = p.id === "agora" ? 7.6 : 6.4;
    const floors = p.id === "agora" ? 2 : 3 + (seed % 2);
    const floorH = 2.7, buildingH = floors * floorH;
    const trim = new THREE.MeshStandardMaterial({color:0x4b4c48,roughness:0.8});
    // Interior floor, end walls, columns and window bays (not an opaque solid box).
    const slab=new THREE.Mesh(new THREE.BoxGeometry(width,0.26,depth),trim);
    slab.position.y=0.25;g.add(slab);
    const footing=new THREE.Mesh(new THREE.BoxGeometry(width+0.5,0.24,depth+0.5),trim);
    footing.position.y=0.12;g.add(footing);
    const roof=new THREE.Mesh(new THREE.BoxGeometry(width+0.24,0.22,depth+0.24),trim);
    roof.position.y=0.35+buildingH+0.11;g.add(roof);
    const sideWall=new THREE.MeshStandardMaterial({color:facade,roughness:0.9});
    for(const side of [-1,1]){
      const wall=new THREE.Mesh(new THREE.BoxGeometry(0.22,buildingH,depth),sideWall);
      wall.position.set(side*(width/2-0.11),0.35+buildingH/2,0);g.add(wall);
    }
    const cols = Math.max(3,Math.floor(width/1.8));
    const winW = 0.72, winH = 1.12, spacing = width/(cols+1);
    const glass = new THREE.MeshStandardMaterial({color:0x546568,roughness:0.08,metalness:0.1,
      transparent:true,opacity:0.36,emissive:0xffc985,emissiveIntensity:0,depthWrite:false});
    windowMats.push(glass);
    const frame = new THREE.MeshStandardMaterial({color:0x4b4c48,roughness:0.78});
    for(let f=0;f<floors;f++){
      const wy=0.55+f*floorH+1.38;
      for(const side of [-1,1]){
        // solid piers between window bays leave real sightlines to the office interior
        for(let c=0;c<=cols;c++){
          const x0=-width/2+c*spacing;
          const pier=new THREE.Mesh(new THREE.BoxGeometry(spacing-winW,winH+0.12,0.16),sideWall);
          pier.position.set(x0+spacing/2,wy,side*(depth/2-0.02));g.add(pier);
        }
        const band=new THREE.Mesh(new THREE.BoxGeometry(width,floorH-winH,0.18),sideWall);
        band.position.set(0,0.55+f*floorH+0.27,side*(depth/2-0.02));g.add(band);
        for(let c=1;c<=cols;c++){
          const wx=-width/2+c*spacing;
          const win=new THREE.Mesh(new THREE.BoxGeometry(winW,winH,0.045),glass);
          win.position.set(wx,wy,side*(depth/2+0.015));g.add(win);
          for(const edge of [-1,1]){
            const post=new THREE.Mesh(new THREE.BoxGeometry(0.07,winH+0.08,0.09),frame);
            post.position.set(wx+edge*(winW/2+0.035),wy,side*(depth/2+0.045));g.add(post);
          }
          const sill=new THREE.Mesh(new THREE.BoxGeometry(winW+0.14,0.07,0.16),frame);
          sill.position.set(wx,wy-winH/2-0.035,side*(depth/2+0.045));g.add(sill);
        }
      }
    }
    // entrance, canopy and sign panel
    const door=new THREE.Mesh(new THREE.BoxGeometry(1.15,2.2,0.12),
      new THREE.MeshStandardMaterial({color:0x292c2b,roughness:0.65}));
    door.position.set(0,1.45,depth/2+0.07);g.add(door);
    const canopy=new THREE.Mesh(new THREE.BoxGeometry(2.1,0.16,0.8),trim);
    canopy.position.set(0,2.63,depth/2+0.38);g.add(canopy);
    const signMat=new THREE.MeshStandardMaterial({color:0x353b3b,roughness:0.8});
    const sign=new THREE.Mesh(new THREE.BoxGeometry(2.4,0.45,0.09),signMat);
    sign.position.set(0,buildingH+0.55,depth/2+0.06);g.add(sign);

    // domain identity remains in a small enamel sign, never a floating beacon
    const hueColor=colorOf(hue);
    const marker=new THREE.Mesh(new THREE.BoxGeometry(0.12,0.26,0.05),
      new THREE.MeshStandardMaterial({color:hueColor,roughness:0.55,metalness:0.15}));
    marker.position.set(-1.55,buildingH+0.55,depth/2+0.115);g.add(marker);

    const lbl=makeLabel(p.name,"#e5e1d8",3.2);
    lbl.position.y=buildingH+1.15;g.add(lbl);
    g.position.set(p.x,0,p.z);
    g.userData={label:lbl,hue,placeId:p.id,buildingH,width,depth,labelY:buildingH+1.15};
    // interior ceiling light per floor, on only after dusk
    const room = new THREE.PointLight(0xffd6a0, 0, Math.max(width, depth) * 1.6, 2);
    room.position.set(0, 0.35 + floorH - 0.3, 0); g.add(room);
    lamps.push({light: room, room: true});
    shadowify(g);mergeStatic(g);
    scene.add(g);pBuildings.set(p.id,g);
  }
}


function buildMistCore(){
  // A grounded civic monument in the Agora; walk to its engraved control plinth.
  const stone = new THREE.MeshStandardMaterial({color:0x77756e,roughness:0.86});
  const bronze = new THREE.MeshStandardMaterial({color:0x75613d,metalness:0.58,roughness:0.48});
  const base = new THREE.Mesh(new THREE.BoxGeometry(2.6,0.5,2.6),stone);
  base.position.y=0.25;scene.add(base);
  const column = new THREE.Mesh(new THREE.BoxGeometry(1.15,1.65,1.15),stone);
  column.position.y=1.32;scene.add(column);
  const cap = new THREE.Mesh(new THREE.BoxGeometry(1.45,0.16,1.45),bronze);
  cap.position.y=2.22;scene.add(cap);
  const plaque = new THREE.Mesh(new THREE.BoxGeometry(0.68,0.92,0.07),bronze);
  plaque.position.set(0,1.35,0.62);scene.add(plaque);
  const label = makeLabel("MIST · WORLD STEWARD", "#e5e1d8", 4.2);
  label.position.set(0,3.05,0);scene.add(label);
  interactables.push({obj:column,kind:"god",label:"MIST · world stewardship"});
}


function buildWorld(){
  scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x9baeb4, 0.0024);
  lamps = []; windowMats = []; colliders = []; envSunKey = ""; city = null; cityKey = ""; lampPool = [];

  camera = new THREE.PerspectiveCamera(55, 1, 0.1, 1200);

  // Physical (Preetham) sky; the same sun direction drives the shadowing key light and
  // the image-based ambient (a PMREM of this sky), so shading, shadows and sky agree.
  sky = G ? GPU.makeSky(G) : new Sky(); sky.scale.setScalar(900); scene.add(sky);
  skySet(sky, "turbidity", 4.5); skySet(sky, "rayleigh", 1.6);
  skySet(sky, "mieCoefficient", 0.004); skySet(sky, "mieDirectionalG", 0.82);

  hemi = new THREE.HemisphereLight(0xbcd3e6, 0x4a4535, 0.6);
  scene.add(hemi);
  sunLight = new THREE.DirectionalLight(0xfff1dc, 3.2);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.set(4096, 4096);
  Object.assign(sunLight.shadow.camera, {left: -62, right: 62, top: 62, bottom: -62, near: 1, far: 260});
  sunLight.shadow.bias = -0.0004; sunLight.shadow.normalBias = 0.035; sunLight.shadow.radius = 3;
  scene.add(sunLight); scene.add(sunLight.target);

  moonMesh = new THREE.Mesh(new THREE.SphereGeometry(4, 24, 16),
    new THREE.MeshBasicMaterial({color: 0xd8dde0, fog: false, transparent: true}));
  scene.add(moonMesh);

  // ground: textured soil/grass inside the town, low hills beyond it for a real horizon
  const groundTex = noiseTexture([82,86,64],34,20,70);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(240, 240),
    new THREE.MeshStandardMaterial({color: 0xffffff, map: groundTex, roughness: 0.97, metalness: 0}));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -0.01; floor.receiveShadow = true; scene.add(floor);
  const hills = new THREE.RingGeometry(118, 600, 160, 24);
  const hp = hills.attributes.position;
  for (let i = 0; i < hp.count; i++){
    const x = hp.getX(i), y = hp.getY(i), r = Math.hypot(x, y), a = Math.atan2(y, x);
    const rise = Math.max(0, (r - 125) / 80);
    hp.setZ(i, Math.min(1, rise) * (6 + 5 * Math.sin(a * 5) + 3 * Math.sin(a * 13 + 1.7)) + rise * 2);
  }
  hills.computeVertexNormals();
  const hillTex = noiseTexture([70,78,56],40,16,60);
  const hillMesh = new THREE.Mesh(hills, new THREE.MeshStandardMaterial({color: 0xffffff, map: hillTex, roughness: 1}));
  hillMesh.rotation.x = -Math.PI / 2; hillMesh.position.y = -0.02; hillMesh.receiveShadow = true; scene.add(hillMesh);

  // Sparse stars appear only at night; no floating decorative particles.
  const starGeo = new THREE.BufferGeometry();
  const N = 300, pos = new Float32Array(N * 3);
  for (let i = 0; i < N; i++){
    const r = 90 + Math.random() * 220, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
    pos[i*3] = r * Math.sin(ph) * Math.cos(th);
    pos[i*3+1] = r * Math.sin(ph) * Math.sin(th) * 0.5 + 25;
    pos[i*3+2] = r * Math.cos(ph);
  }
  starGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  stars = new THREE.Points(starGeo, new THREE.PointsMaterial({color: 0xe6e4d8, size: 0.16,
    sizeAttenuation: true, transparent: true, opacity: 0}));
  scene.add(stars);


  buildMistCore();
  buildBuildings();
  buildHallTable();
  syncAgents();
  shadowify(scene);
  for (const [pid, arr] of Object.entries(PLACE_ROLE)){
    const b = pBuildings.get(pid);
    if (b){ const [kind, label, param] = arr; interactables.push({obj: b, kind, label, params: param ? [param] : []}); }
  }

  avatar = new THREE.Group();
  avBody = new THREE.Group();
  const youCloth = new THREE.MeshStandardMaterial({color:0x354044,roughness:0.9});
  const youPants = new THREE.MeshStandardMaterial({color:0x272d31,roughness:0.92});
  const youSkin = new THREE.MeshStandardMaterial({color:0xa47b65,roughness:0.85});
  const youHair = new THREE.MeshStandardMaterial({color:0x292522,roughness:0.95});
  const youTorso = new THREE.Mesh(new THREE.BoxGeometry(0.48,0.62,0.28),youCloth);
  youTorso.position.y=1.30;avBody.add(youTorso);
  const pelvis = new THREE.Mesh(new THREE.BoxGeometry(0.36,0.25,0.23),youPants);
  pelvis.position.y=0.94;avBody.add(pelvis);
  const youHead = new THREE.Mesh(new THREE.SphereGeometry(0.135,20,16),youSkin);
  youHead.scale.set(0.86,1.18,0.92);youHead.position.set(0,1.84,0.02);avBody.add(youHead);
  const cap = new THREE.Mesh(new THREE.SphereGeometry(0.14,16,10,0,Math.PI*2,0,Math.PI*0.48),youHair);
  cap.scale.set(0.9,0.78,0.95);cap.position.set(0,1.91,-0.005);avBody.add(cap);
  const arms=[],legs=[];
  for(const side of [-1,1]){
    const arm=new THREE.Group(); arm.position.set(side*0.28,1.52,0);
    const upper=new THREE.Mesh(new THREE.CylinderGeometry(0.075,0.085,0.34,9),youCloth);
    upper.position.y=-0.20;arm.add(upper);
    const fore=new THREE.Mesh(new THREE.CylinderGeometry(0.058,0.07,0.30,9),youCloth);
    fore.position.y=-0.51;arm.add(fore);
    const hand=new THREE.Mesh(new THREE.SphereGeometry(0.06,8,8),youSkin);hand.position.y=-0.70;arm.add(hand);
    avBody.add(arm);arms.push(arm);
    const leg=new THREE.Group();leg.position.set(side*0.12,0.88,0);
    const thigh=new THREE.Mesh(new THREE.CylinderGeometry(0.10,0.085,0.40,9),youPants);
    thigh.position.y=-0.20;leg.add(thigh);
    const shin=new THREE.Mesh(new THREE.CylinderGeometry(0.065,0.08,0.38,9),youPants);
    shin.position.y=-0.57;leg.add(shin);
    const shoe=new THREE.Mesh(new THREE.BoxGeometry(0.13,0.09,0.23),
      new THREE.MeshStandardMaterial({color:0x17191a,roughness:0.88}));
    shoe.position.set(0,-0.79,0.04);leg.add(shoe);
    avBody.add(leg);legs.push(leg);
  }
  avatar.add(avBody);
  avatar.userData={arms,legs};
  const youLabel=makeLabel("you","#e5e1d8",1.5);
  youLabel.position.y=2.14;avatar.add(youLabel);
  avatar.position.set(PLAYER_START.x,0,PLAYER_START.z);scene.add(avatar);
}

function syncAgents(){
  const pmap = {}, colmap = {};
  if (pantheon && Array.isArray(pantheon.agents)) pantheon.agents.forEach(p => pmap[p.name.toLowerCase()] = p);
  colonyAgents().forEach(a => { colmap[a.name.toLowerCase()] = a; });

  const names = new Set([...Object.keys(pmap), ...Object.keys(colmap)]);
  const cur = [...beings.keys()];
  const changed = names.size !== cur.length || [...names].some(n => !beings.has(n));

  if (changed){
    for (const {group} of beings.values()) scene.remove(group);
    beings.clear();
    interactables = interactables.filter(it => it.kind !== "talk");
    const n = Math.max(1, names.size);
    [...names].forEach((name, i) => {
      const a = colmap[name] || pmap[name];
      const g = buildBeing(a);
      const p = pmap[name];
      if (p){
        g.position.set(p.x, 0, p.z);
        g.userData.targetX=p.x;g.userData.targetZ=p.z;
        if (p.fx || p.fz) g.rotation.y = Math.atan2(p.fx, p.fz);
      } else {
        const ang = Math.PI * (0.12 + 0.76 * (i / Math.max(1, n - 1)));
        const r = 6.5 + (i % 3) * 1.4;
        g.position.set(Math.sin(ang) * r, 0, -Math.cos(ang) * r - 1.5);
      }
      scene.add(g);
      beings.set(name, {group: g, agent: a, p: p});
      interactables.push({obj: g, kind: "talk", mind: a.name, label: "talk to " + a.name, params: [a.name]});
    });
  } else {
    beings.forEach((b, name) => {
      if (colmap[name]) b.agent = colmap[name];
      const p = pmap[name];
      b.p = p || b.p;
      if (p){
        b.group.userData.targetX=p.x;b.group.userData.targetZ=p.z;
        if (p.fx || p.fz) b.group.rotation.y = Math.atan2(p.fx, p.fz);
      }
    });
  }
  syncWorkstations();
}

function syncThoughts(){
  if(!pantheon||!pantheon.minds||!Array.isArray(pantheon.agents))return;
  for(const p of pantheon.agents){
    if(!p.thought||lastThought.get(p.name)===p.thought)continue;
    const first=!lastThought.has(p.name);
    lastThought.set(p.name,p.thought);
    if(first)continue;   // do not replay old thoughts on page load
    if(!faceBubbles.some(b=>b.name.toLowerCase()===p.name.toLowerCase()))addFaceBubble(p.name,p.thought,"thinking",6500);
  }
}

let decreeShown = 0;
function showDecree(e, now){
  if (!rootEl || e.ts <= decreeShown || (now / 1000) - e.ts > 20) return;
  decreeShown = e.ts;
  let el = rootEl.querySelector(".w3d-decree");
  if (!el){
    el = document.createElement("div"); el.className = "w3d-decree";
    el.style.cssText = "position:absolute;left:50%;top:64px;transform:translateX(-50%);max-width:70%;padding:10px 18px;" +
      "border-radius:10px;background:rgba(20,16,6,.78);border:1px solid #d9b45a;color:#f3e3b5;font:600 15px/1.4 ui-sans-serif,system-ui;" +
      "text-align:center;box-shadow:0 0 24px rgba(217,180,90,.35);pointer-events:none;transition:opacity .6s";
    rootEl.appendChild(el);
  }
  el.innerHTML = `<div style="font:700 11px ui-monospace,Menlo,monospace;letter-spacing:.14em;color:#d9b45a">` +
    `${e.to ? "CREATOR · TO " + esc(String(e.to).toUpperCase()) : "CREATOR DECREES"}</div>${esc(e.text)}`;
  el.style.opacity = "1";
  clearTimeout(el._t); el._t = setTimeout(() => { el.style.opacity = "0"; }, 12000);
}

function syncTalk(){
  if (!pantheon || !Array.isArray(pantheon.talk)) return;
  const now = Date.now();
  for (let i = talkBubbles.length - 1; i >= 0; i--){
    if (talkBubbles[i].until < now){
      if(talkBubbles[i].face)removeFaceBubble(talkBubbles[i].face);
      if(talkBubbles[i].sprite)scene.remove(talkBubbles[i].sprite);
      talkBubbles.splice(i, 1);
    }
  }
  for (const e of pantheon.talk){
    if (e.kind === "god"){ showDecree(e, now); continue; }   // the creator has no body to bubble over
    if ((now / 1000) - e.ts > 7) continue;
    const key = e.name + "|" + e.ts;
    if (talkBubbles.some(b => b.key === key)) continue;
    const old=talkBubbles.findIndex(b=>String(b.name||"").toLowerCase()===String(e.name).toLowerCase());
    if(old>=0){if(talkBubbles[old].face)removeFaceBubble(talkBubbles[old].face);talkBubbles.splice(old,1);}
    const b = beings.get(e.name.toLowerCase());
    if (!b) continue;
    const kind=e.kind==="assembly"?"Hall conversation":(e.to?"to "+e.to:"said aloud");
    const face=addFaceBubble(e.name,String(e.text||""),kind,7500);
    talkBubbles.push({face,until:now+7000,key,name:e.name});
  }
}

/* ---------------------------------------------------------------- camera & motion */
let footprintCache=null,footprintKey=null;
function footprints(){
  if(footprintKey===layout)return footprintCache;
  footprintKey=layout;
  const rects=(layout.colliders||[]).filter(c=>c.type==="box"&&Math.min(c.x1-c.x0,c.z1-c.z0)>=1.5)
    .map(c=>[c.x0,c.z0,c.x1,c.z1]);
  for(const h of layout.houses||[]){
    const turned=h.facing==="+x"||h.facing==="-x",w=turned?h.depth:h.width,d=turned?h.width:h.depth;
    rects.push([h.x-w/2,h.z-d/2,h.x+w/2,h.z+d/2]);
  }
  return footprintCache=rects;
}

function cameraFromAvatar(dt){
  const target = avatar.position.clone();
  target.y += 1.2;
  const off = new THREE.Vector3(
    Math.sin(theta) * Math.cos(phi),
    Math.sin(phi),
    Math.cos(theta) * Math.cos(phi)).multiplyScalar(radius);
  let ideal = target.clone().add(off);

  // Keep the trailing camera outside building shells instead of letting the
  // office facade fill the entire view when the avatar nears a doorway.
  if(pBuildings.size){
    // Raycaster needs current world matrices; on the initial camera frame the
    // renderer has not yet performed its first matrix update.
    if(!cameraReady) scene.updateMatrixWorld(true);
    const dir=off.clone().normalize();
    const ray=new THREE.Raycaster(target,dir,0.25,radius);
    ray.camera=camera; // Sprite labels in building groups need the active camera for raycast.
    const hits=ray.intersectObjects([...pBuildings.values()],true);
    if(hits.length) ideal=target.clone().addScaledVector(dir,Math.max(2.4,hits[0].distance-0.55));
  }
  // Generated lot buildings and houses come from the town plan: pull the camera in front of
  // any footprint it would otherwise sit inside (unless the visitor is inside it too).
  if(layout){
    const dir=ideal.clone().sub(target), full=dir.length(); dir.normalize();
    const solids=footprints();
    const inside=(x,z)=>solids.some(r=>x>r[0]&&x<r[2]&&z>r[1]&&z<r[3]&&
      !(avatar.position.x>r[0]&&avatar.position.x<r[2]&&avatar.position.z>r[1]&&avatar.position.z<r[3]));
    for(let d=0.6;d<=full;d+=0.3){
      const p=target.clone().addScaledVector(dir,d);
      if(p.y<9&&inside(p.x,p.z)){ideal=target.clone().addScaledVector(dir,Math.max(1.6,d-0.5));break;}
    }
  }
  if(!cameraReady){camera.position.copy(ideal);cameraReady=true;}
  else camera.position.lerp(ideal,1-Math.exp(-Math.max(0.001,dt||0.016)*7));
  camera.lookAt(target);
}

function forward(){ return new THREE.Vector3(-Math.sin(theta), 0, -Math.cos(theta)); }
function right(){ const f = forward(); return new THREE.Vector3(-f.z, 0, f.x); }

const AVATAR_R = 0.32;

/* Character controller: a circle pushed out of every server-published collider (walls,
 * desks, monument, trees, generated objects) and out of the residents' bodies. Pushing
 * along the contact normal makes the avatar slide along walls instead of sticking. */
function resolveCollisions(x, z){
  for (let iter = 0; iter < 4; iter++){
    let moved = false;
    for (const c of colliders){
      if (c.type === "box"){
        if (x < c.x0 - AVATAR_R || x > c.x1 + AVATAR_R || z < c.z0 - AVATAR_R || z > c.z1 + AVATAR_R) continue;
        const nx = Math.max(c.x0, Math.min(x, c.x1)), nz = Math.max(c.z0, Math.min(z, c.z1));
        let dx = x - nx, dz = z - nz, d = Math.hypot(dx, dz);
        if (d >= AVATAR_R) continue;
        if (d < 1e-6){   // centre inside the box: leave by the nearest face
          const pen = [[x - c.x0, -1, 0], [c.x1 - x, 1, 0], [z - c.z0, 0, -1], [c.z1 - z, 0, 1]].sort((a, b) => a[0] - b[0])[0];
          x += pen[1] * (pen[0] + AVATAR_R); z += pen[2] * (pen[0] + AVATAR_R);
        } else { x += dx / d * (AVATAR_R - d); z += dz / d * (AVATAR_R - d); }
        moved = true;
      } else {
        const dx = x - c.x, dz = z - c.z, d = Math.hypot(dx, dz), min = c.r + AVATAR_R;
        if (d >= min || d < 1e-6) continue;
        x += dx / d * (min - d); z += dz / d * (min - d); moved = true;
      }
    }
    for (const {group} of beings.values()){
      const dx = x - group.position.x, dz = z - group.position.z, d = Math.hypot(dx, dz), min = AVATAR_R + 0.3;
      if (d >= min || d < 1e-6) continue;
      x += dx / d * (min - d); z += dz / d * (min - d); moved = true;
    }
    if (!moved) break;
  }
  return [x, z];
}

/* Where a resident is on its server-routed path right now (server clock). */
function pathPosition(p){
  if (!p || !Array.isArray(p.path) || p.path.length < 2) return null;
  const now = Date.now() / 1000 + serverOffset;
  const span = Math.max(0.001, p.arrive_at - p.depart_at);
  const t = Math.min(1, Math.max(0, (now - p.depart_at) / span));
  let total = 0;
  for (let i = 1; i < p.path.length; i++) total += Math.hypot(p.path[i][0]-p.path[i-1][0], p.path[i][1]-p.path[i-1][1]);
  let dist = total * t;
  for (let i = 1; i < p.path.length; i++){
    const a = p.path[i-1], b = p.path[i], seg = Math.hypot(b[0]-a[0], b[1]-a[1]);
    if (dist <= seg || i === p.path.length - 1){
      const k = seg ? Math.min(1, dist / seg) : 1;
      return {x: a[0] + (b[0]-a[0]) * k, z: a[1] + (b[1]-a[1]) * k,
              fx: seg ? (b[0]-a[0]) / seg : 0, fz: seg ? (b[1]-a[1]) / seg : 0, moving: t < 1};
    }
    dist -= seg;
  }
  return null;
}

function step(dt){
  const move = new THREE.Vector3();
  const f = forward(), r = right();
  if (keys.w || keys.ArrowUp) move.add(f);
  if (keys.s || keys.ArrowDown) move.sub(f);
  if (keys.a || keys.ArrowLeft) move.sub(r);
  if (keys.d || keys.ArrowRight) move.add(r);
  if (move.lengthSq() > 0){
    move.normalize().multiplyScalar(AVATAR_SPEED * dt);
    const nx=Math.max(-WORLD_R,Math.min(WORLD_R,avatar.position.x+move.x));
    const nz=Math.max(-WORLD_R,Math.min(WORLD_R,avatar.position.z+move.z));
    const [cx, cz] = resolveCollisions(nx, nz);
    avatar.position.set(cx, 0, cz);
    const targetYaw = Math.atan2(move.x, move.z);
    avatar.rotation.y += (targetYaw - avatar.rotation.y) * 0.12;
  }
}

/* ---------------------------------------------------------------- interaction */
function nearestInteractable(){
  let best = null, bd = Infinity;
  for (const it of interactables){
    const dx = avatar.position.x - it.obj.position.x;
    const dz = avatar.position.z - it.obj.position.z;
    const d = Math.hypot(dx, dz);
    if (d < REACH && d < bd){ bd = d; best = it; }
  }
  return best;
}

function zoneName(){
  let best = null, bd = 1e9;
  for (const p of placesList()){
    const d = Math.hypot(avatar.position.x - p.x, avatar.position.z - p.z);
    if (d < bd){ bd = d; best = p; }
  }
  return best && bd < 7.5 ? best.name.toLowerCase() : "the between";
}

function nearestBeing(){
  let best=null,bd=REACH;
  for(const [key,b] of beings){
    const d=Math.hypot(avatar.position.x-b.group.position.x,avatar.position.z-b.group.position.z);
    if(d<bd){bd=d;best=(b.agent&&b.agent.name)||key;}
  }
  return best;
}

function promptText(){
  if (faceVoice.busy) return "speaking with " + faceVoice.name + "…";
  if (faceVoice.capture) return "[V] finish speaking to " + faceVoice.name;
  const person=nearestBeing();
  if (near && near.kind === "talk"){
    const b = beings.get(String(near.mind).toLowerCase());
    const goal = b && b.p && b.p.goal ? " — goal: " + b.p.goal : "";
    return "[E] text · [V] speak face-to-face with " + near.mind + " · [M] mind" + goal;
  }
  if (person) return (near ? "[E] " + near.label + " · " : "") + "[V] speak face-to-face with " + person;
  if (!near) return "";
  return "[E] " + near.label;
}

function addFaceBubble(name, text, voiceLabel="", timeout=16000){
  if (!hud.bubbleLayer) return null;
  for(const old of faceBubbles.slice()) if(old.name.toLowerCase()===name.toLowerCase()) removeFaceBubble(old);
  const el=document.createElement("div"); el.className="w3d-speech-bubble";
  const head=document.createElement("div"); head.className="w3d-speech-head";
  const who=document.createElement("b"); who.textContent=name; head.appendChild(who);
  if(voiceLabel){const voice=document.createElement("span");voice.textContent=voiceLabel;head.appendChild(voice);}
  const body=document.createElement("div");body.className="w3d-speech-text";body.textContent=text;
  el.append(head,body);hud.bubbleLayer.appendChild(el);
  const bubble={name,el,until:timeout?Date.now()+timeout:0,audio:null,url:null};
  faceBubbles.push(bubble);updateFaceBubble(bubble);return bubble;
}

function updateFaceBubble(bubble){
  if(!camera||!rootEl||!bubble.el)return;
  const being=beings.get(bubble.name.toLowerCase());
  if(!being){bubble.el.style.display="none";return;}
  const ud=being.group.userData||{};
  const point=new THREE.Vector3(being.group.position.x,(ud.height||1.75)+0.62,being.group.position.z).project(camera);
  const x=(point.x*0.5+0.5)*rootEl.clientWidth;
  const y=(-point.y*0.5+0.5)*rootEl.clientHeight;
  const visible=point.z<1 && x>0 && x<rootEl.clientWidth && y>0 && y<rootEl.clientHeight;
  bubble.el.style.display=visible?"block":"none";
  if(visible){bubble.el.style.left=x+"px";bubble.el.style.top=y+"px";}
}

function updateFaceBubbles(now){
  for(const bubble of faceBubbles.slice()){
    if(bubble.until&&bubble.until<now){removeFaceBubble(bubble);continue;}
    updateFaceBubble(bubble);
  }
}

function removeFaceBubble(bubble){
  if(bubble.audio){bubble.audio.pause();bubble.audio.src="";bubble.audio=null;}
  if(bubble.url){URL.revokeObjectURL(bubble.url);bubble.url=null;}
  if(bubble.el&&bubble.el.parentNode)bubble.el.parentNode.removeChild(bubble.el);
  faceBubbles=faceBubbles.filter(x=>x!==bubble);
}

async function startFaceVoice(name){
  if(faceVoice.busy||faceVoice.capture)return;
  faceVoice.name=name;faceVoice.busy=true;
  const bubble=addFaceBubble(name,"Allow microphone access, then speak.");
  try{
    const capture=await startVoiceCapture({onLimit:()=>{if(faceVoice.capture)finishFaceVoice();}});
    if(disposed){await capture.cancel();return;}
    faceVoice.capture=capture;faceVoice.busy=false;
    if(bubble){bubble.el.querySelector(".w3d-speech-text").textContent="Listening… press V to send";bubble.until=0;}
  }catch(e){
    faceVoice.busy=false;
    if(bubble){bubble.el.querySelector(".w3d-speech-text").textContent=e.message||"Microphone unavailable";bubble.until=Date.now()+6500;}
    faceVoice.name=null;
  }
}

async function finishFaceVoice(){
  if(!faceVoice.capture||faceVoice.busy)return;
  const name=faceVoice.name,capture=faceVoice.capture;
  faceVoice.capture=null;faceVoice.busy=true;
  const bubble=addFaceBubble(name,"Thinking…");
  const controller=new AbortController();faceVoice.abort=controller;
  const timer=setTimeout(()=>controller.abort(),180000);
  try{
    const wav=await capture.stop();if(!wav)return;
    const data=await sendVoiceTurn(name,wav,controller.signal);
    if(disposed||!rootEl)return;
    const reply=data.reply||"I have nothing to say.";
    const replyBubble=addFaceBubble(name,reply,data.voice_label?"Kokoro · "+data.voice_label:"Kokoro voice",0);
    if(data.voice_error){
      if(replyBubble){replyBubble.el.querySelector(".w3d-speech-text").textContent=reply+" (voice playback unavailable)";replyBubble.until=Date.now()+16000;}
    }else{
      const url=audioURLFromResponse(data);
      if(url&&replyBubble){
        replyBubble.url=url;
        const audio=new Audio(url);replyBubble.audio=audio;
        const play=document.createElement("button");play.className="w3d-speech-play";play.type="button";play.textContent="▶ replay";
        play.addEventListener("click",ev=>{ev.stopPropagation();audio.currentTime=0;audio.play().catch(()=>{});});
        replyBubble.el.appendChild(play);
        audio.onended=()=>{replyBubble.until=Date.now()+4500;};
        audio.play().catch(()=>{play.textContent="▶ tap to hear";});
        setTimeout(()=>{if(replyBubble.until===0)replyBubble.until=Date.now()+16000;},45000);
      }else if(replyBubble){replyBubble.until=Date.now()+16000;}
    }
  }catch(e){
    if(bubble&&bubble.el&&bubble.el.isConnected){bubble.el.querySelector(".w3d-speech-text").textContent=(e&&e.message)||"Voice turn failed";bubble.until=Date.now()+7000;}
  }finally{
    clearTimeout(timer);faceVoice.abort=null;faceVoice.busy=false;faceVoice.name=null;
  }
}

function clearFaceVoice(){
  if(faceVoice.abort)faceVoice.abort.abort();
  if(faceVoice.capture)faceVoice.capture.cancel();
  faceVoice={name:null,capture:null,busy:false,abort:null};
  for(const bubble of faceBubbles.slice())removeFaceBubble(bubble);
}

/* ---------------------------------------------------------------- the screens */
const workScreen = {
  data: null, err: null, domain: null,
  async mount(ctx){
    this.domain = (ctx.route && ctx.route.params && ctx.route.params[0]) || "world";
    await this.load(); this.render(ctx);
  },
  async update(ctx){ await this.load(); this.render(ctx); },
  unmount(){ this.data = null; this.err = null; },
  async load(){
    const r = await getJSON("/api/colony/domain/" + encodeURIComponent(this.domain), {timeout: 30000});
    if (r.ok){ this.data = r.data; this.err = null; } else this.err = r.error || "unreadable";
  },
  render(ctx){
    if (this.err){ paint(ctx.root, panel("work", errbox(this.err), {cls: "c12 bad"})); return; }
    if (!this.data){ paint(ctx.root, panel("work", note("reading the pool…"), {cls: "c12"})); return; }
    const tasks = this.data.tasks || [];
    const rows = tasks.map(t => [
      chip("t" + esc(t.id), t.status === "open" ? "on" : (t.status === "solved" ? "solid" : "")),
      num(t.difficulty), num(t.reward),
      chip(esc(t.status || "?"), ""),
      t.claimed_by_name ? esc(t.claimed_by_name) : "—",
      esc(String(t.question || "").slice(0, 110)),
    ]);
    paint(ctx.root, panel("the " + esc(this.data.domain) + " pool · " + tasks.length + " tasks",
      table(["task", "diff", "reward", "status", "held by", "question"], rows,
        {scroll: "tall", key: "work", empty: "no tasks in this domain"}),
      {cls: "c12", meta: num(this.data.open) + " open"}));
  },
};

const SCREENS = {
  talk:     {mod: intercomView, title: p => "talk · " + esc(p[0])},
  mind:     {mod: ciView,      title: p => esc(p[0]) + " · mind"},
  computer: {mod: ciView,      title: p => esc(p[0]) + " · workstation"},
  colony:   {mod: colonyView,  title: () => "the colony"},
  machine:  {mod: worldView,   title: () => "the machine"},
  assemble: {mod: assemblyView, title: () => "the room"},
  god:      {mod: mistView,    title: () => "MIST · the god"},
  builder:  {mod: builderView, title: () => "world · Vinod Chanda's asset builder"},
  work:     {mod: workScreen, title: p => "work · " + esc(p[0] || "?")},
  house:    {mod: ciView,      title: p => esc(p[0]) + "’s house · mind"},
};

function openOverlay(kind, params = []){
  if (overlay) closeOverlay();
  const spec = SCREENS[kind];
  if (!spec) return;
  const root = document.createElement("div");
  root.className = "w3d-overlay";
  root.innerHTML = `<div class="w3d-screen">
    <div class="w3d-screen-head"><span class="w3d-screen-title">${spec.title(params)}</span>
      <span class="w3d-screen-close" data-w3d-close>✕ &nbsp;esc</span></div>
    <div class="overlay-body"></div>
  </div>`;
  document.body.appendChild(root);
  const body = root.querySelector(".overlay-body");
  overlay = {module: spec.mod, body, root, kind};
  spec.mod.mount({root: body, route: {params, view: kind}});
  root.addEventListener("click", ev => { if (ev.target.closest("[data-w3d-close]")) closeOverlay(); });
  if (hud.prompt) hud.prompt.style.display = "none";
}

function closeOverlay(){
  if (!overlay) return;
  try { if (overlay.module.unmount) overlay.module.unmount({root: overlay.body}); } catch (e) {}
  if (overlay.root.parentNode) overlay.root.parentNode.removeChild(overlay.root);
  overlay = null;
  if (hud.prompt) hud.prompt.style.display = "";
}

/* ---------------------------------------------------------------- HUD */
function buildHud(){
  const mk = cls => { const el = document.createElement("div"); el.className = cls; rootEl.appendChild(el); return el; };
  hud.crosshair = mk("w3d-crosshair");
  hud.zone = mk("w3d-zone");
  hud.compass = mk("w3d-compass");
  hud.brain = mk("w3d-brain");
  hud.prompt = mk("w3d-prompt");
  hud.controls = mk("w3d-controls");
  hud.bubbleLayer = mk("w3d-bubble-layer");
  hud.controls.innerHTML = "click to focus · walk <b>WASD</b> · look <b>drag</b> · interact <b>E</b> · voice <b>V</b> · mind <b>M</b> · brain <b>B</b> · quality <b>Q</b> · close <b>esc</b> · <button type=\"button\" data-world-builder style=\"margin-left:8px;padding:5px 9px;background:#20323a;color:#dce9e6;border:1px solid #617b7b;border-radius:4px;cursor:pointer\">Vinod · World Builder</button>";
  hud.controls.querySelector("[data-world-builder]").addEventListener("click", e => { e.stopPropagation(); openOverlay("builder"); });
}

/* ---------------------------------------------------------------- events */
function bindInput(){
  window.addEventListener("keydown", e => {
    if (overlay){
      if (e.key === "Escape"){ closeOverlay(); e.preventDefault(); }
      return;
    }
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (key === "v"){
      if (!e.repeat){
        if (faceVoice.capture) finishFaceVoice();
        else { const person=nearestBeing(); if(person)startFaceVoice(person); }
      }
      e.preventDefault(); return;
    }
    if (["w","a","s","d","ArrowUp","ArrowDown","ArrowLeft","ArrowRight"," "].includes(key)){
      keys[key] = true; e.preventDefault();
    }
    if (key === "e"){ if (near) openOverlay(near.kind, near.params || []); }
    if (key === "m"){ if (near && near.kind === "talk") openOverlay("mind", [near.mind]); }
    if (key === "b"){ toggleMinds(); }
    if (key === "q"){ quality = quality === "high" ? "fast" : "high"; }
    if (e.key === "Escape"){ closeOverlay(); }
  });
  window.addEventListener("keyup", e => {
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    keys[key] = false;
  });
  window.addEventListener("blur", () => { keys = {}; });

  renderer.domElement.tabIndex = 0;
  renderer.domElement.setAttribute("aria-label", "MIST world. Click here to focus, then use WASD to walk.");
  renderer.domElement.addEventListener("pointerdown", e => {
    renderer.domElement.focus({preventScroll:true});
    dragging = true; movedOnDrag = 0; lastX = e.clientX; lastY = e.clientY;
  });
  window.addEventListener("pointermove", e => {
    if (!dragging || overlay) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    movedOnDrag += Math.abs(dx) + Math.abs(dy);
    theta -= dx * 0.005;
    phi = Math.max(0.12, Math.min(1.15, phi + dy * 0.005));
    lastX = e.clientX; lastY = e.clientY;
  });
  window.addEventListener("pointerup", e => {
    if (!dragging) return;
    dragging = false;
    if (movedOnDrag < 6 && !overlay){
      const rect = renderer.domElement.getBoundingClientRect();
      const ndcX = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const ndcY = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      const it = raycastInteract(ndcX, ndcY);
      if (it) openOverlay(it.kind, it.params || []);
    }
  });
  renderer.domElement.addEventListener("wheel", e => {
    radius = Math.max(3, Math.min(18, radius + e.deltaY * 0.01));
    e.preventDefault();
  }, {passive: false});
}

function raycastInteract(ndcX, ndcY){
  const ray = new THREE.Raycaster();
  ray.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);
  const hits = ray.intersectObjects(interactables.map(i => i.obj), true);
  if (!hits.length) return null;
  let node = hits[0].object;
  for (let k = 0; k < 8 && node; k++){
    for (const it of interactables){ if (it.obj === node) return it; }
    node = node.parent;
  }
  return null;
}

/* ---------------------------------------------------------------- day / night */
const _sunDir = new THREE.Vector3(), _moonDir = new THREE.Vector3();
function applyDayNight(){
  const hour = hourOverride != null ? hourOverride : (pantheon && pantheon.clock) ? pantheon.clock.hour : 12;
  // Sun on a tilted arc: rises in the east at 6, peaks ~58° at noon, sets in the west at 18.
  const ang = Math.PI * (hour - 6) / 12;
  const elev = Math.sin(ang) * 58 * Math.PI / 180;
  const azim = Math.PI * 0.5 - ang;  // east (+x) → south → west (−x)
  _sunDir.set(Math.cos(elev) * Math.cos(azim), Math.sin(elev), Math.cos(elev) * Math.sin(azim) * 0.55 - 0.35).normalize();
  const day = THREE.MathUtils.smoothstep(_sunDir.y, -0.08, 0.18);      // 0 night … 1 day
  const golden = 1 - THREE.MathUtils.smoothstep(_sunDir.y, 0.02, 0.35); // warm light near horizon

  if (sky){
    skySet(sky, "sunPosition", _sunDir);
    skySet(sky, "rayleigh", 1.2 + golden * 1.4);
  }
  if (sunLight){
    const focus = avatar ? avatar.position : new THREE.Vector3();
    sunLight.target.position.set(focus.x, 0, focus.z);
    // By night the same key light becomes the moon: opposite the sun, cool and dim.
    const moonUp = _sunDir.y < 0;
    const keyDir = moonUp ? _moonDir.copy(_sunDir).negate().setY(Math.max(0.25, -_sunDir.y)).normalize() : _sunDir;
    sunLight.position.copy(sunLight.target.position).addScaledVector(keyDir, 120);
    if (moonUp){ sunLight.intensity = 0.55 * (1 - day); sunLight.color.setRGB(0.62, 0.72, 0.95); }
    else { sunLight.intensity = 2.7 * day + 0.1; sunLight.color.setRGB(1, 0.93 - golden * 0.22, 0.84 - golden * 0.42); }
    sunLight.castShadow = true;
  }
  if (hemi){
    hemi.intensity = 0.24 + day * 0.4;
    hemi.color.setRGB(0.42 + day * 0.32, 0.5 + day * 0.32, 0.62 + day * 0.3);
  }
  if (scene.fog){
    const nightFog = new THREE.Color(0x0e161c), dayFog = new THREE.Color(0xa9bcc6), duskFog = new THREE.Color(0xc9a98c);
    scene.fog.color.copy(nightFog).lerp(dayFog, day).lerp(duskFog, golden * day * 0.6);
  }
  if (renderer) renderer.toneMappingExposure = 0.7 - day * 0.08;
  if (stars) stars.material.opacity = Math.max(0, 0.85 - day * 1.6);
  if (moonMesh){
    moonMesh.position.copy(_moonDir.copy(_sunDir).negate().setY(Math.max(0.25, -_sunDir.y)).normalize()).multiplyScalar(380);
    moonMesh.position.y = Math.max(-40, moonMesh.position.y);
    moonMesh.material.opacity = 1 - day;
  }
  // Lamps and windows come on at dusk.
  const dark = 1 - day;
  darkness = dark;
  for (const l of lamps){
    l.light.intensity = (l.room ? 9 : 22) * dark;
    if (l.lamp) l.lamp.material.emissiveIntensity = 0.2 + dark * 3;
  }
  for (const m of windowMats) m.emissiveIntensity = dark * 0.9;

  // Re-light the image-based ambient only when the sun has moved noticeably.
  const key = _sunDir.x.toFixed(2) + "," + _sunDir.y.toFixed(2);
  if (renderer && key !== envSunKey){
    envSunKey = key;
    if (!envGen){
      envGen = G ? new G.T.PMREMGenerator(renderer) : new THREE.PMREMGenerator(renderer);
      envScene = new THREE.Scene(); envSky = G ? GPU.makeSky(G) : new Sky(); envSky.scale.setScalar(10); envScene.add(envSky);
    }
    for (const k of ["turbidity", "rayleigh", "mieCoefficient", "mieDirectionalG", "sunPosition"])
      skySet(envSky, k, skyGet(sky, k));
    skySet(envSky, "cloudCoverage", 0);      // r187's Sky paints clouds; baked into the PMREM they flood every surface with white
    skySet(envSky, "showSunDisc", 0);        // a one-pixel sun in the PMREM would light every surface like a lamp
    if (envRT) envRT.dispose();
    envRT = envGen.fromScene(envScene, 0, 0.1, 100);
    scene.environment = envRT.texture;
    scene.environmentIntensity = 0.5;       // r187's sky is brighter than r160's; this restores the original exposure
  }
}

/* ---------------------------------------------------------------- loop */
function animate(){
  if (disposed) return;
  raf = requestAnimationFrame(animate);
  const dt = Math.min(0.05, clock.getDelta());
  const now = Date.now();
  const t = clock.elapsedTime;

  if (!overlay) step(dt);

  if (!beings.size && (colonyAgents().length || (pantheon && pantheon.agents && pantheon.agents.length))) syncAgents();
  syncTalk();
  syncThoughts();
  applyDayNight();
  if (city) city.update(dt, darkness);
  updateLampPool(now);

  beings.forEach(({group, agent, p}) => {
    const pr = presence(agent, now);
    const ud=group.userData;
    const onPath = pathPosition(p);
    if (onPath){
      group.position.x += (onPath.x - group.position.x) * 0.3;
      group.position.z += (onPath.z - group.position.z) * 0.3;
      if (onPath.moving && (onPath.fx || onPath.fz)){
        const yaw = Math.atan2(onPath.fx, onPath.fz);
        let dy = yaw - group.rotation.y; dy = Math.atan2(Math.sin(dy), Math.cos(dy));
        group.rotation.y += dy * 0.15;
      }
    } else if(ud.targetX!=null){
      group.position.x += (ud.targetX-group.position.x)*0.08;
      group.position.z += (ud.targetZ-group.position.z)*0.08;
    }
    const act = p ? (p.activity || "") : "";
    const seated = /sitting in a CI gathering/.test(act);
    setBeingSeated(group,seated);
    const moving = /walking|running/.test(act);
    const running = /running/.test(act);
    const cadence = t * (running ? 9 : 5.6);
    const sw = moving ? Math.sin(cadence) : 0;
    const bob = moving ? Math.abs(Math.sin(cadence))*(running?0.11:0.055) : Math.sin(t*1.6+group.position.x)*0.012;
    group.position.y += (bob-group.position.y)*0.35;
    group.rotation.x += ((moving?(running?0.08:0.035):0)-group.rotation.x)*0.08;
    if(!seated){
      ud.arms.forEach((arm,i)=>{
        const swing = moving ? sw*(i===0?0.24:-0.24) : 0;
        arm.upper.rotation.x += (swing-arm.upper.rotation.x)*0.22;
        arm.lower.rotation.x += (swing*0.45-arm.lower.rotation.x)*0.22;
      });
      ud.legs.forEach((leg,i)=>{
        const swing = moving ? sw*(i===0?-0.28:0.28) : 0;
        leg.thigh.rotation.x += (swing-leg.thigh.rotation.x)*0.22;
        leg.shin.rotation.x += (Math.max(0,swing)*0.35-leg.shin.rotation.x)*0.22;
      });
    }
    ud.label.position.y = ud.height + 0.20 + Math.sin(t*1.1+group.position.x)*0.025;
  });

  interactables.forEach(it => {
    if (it.obj.userData.label) it.obj.userData.label.position.y = (it.obj.userData.labelY || 3.0)
      + Math.sin(t * 0.8 + it.obj.position.x) * 0.025;
  });

  near = nearestInteractable();
  if (hud.prompt){
    const txt = promptText();
    hud.prompt.textContent = txt;
    hud.prompt.style.display = (txt && !overlay) ? "" : "none";
  }
  if (hud.zone) hud.zone.textContent = zoneName();
  if (hud.brain){
    hud.brain.textContent = pantheon
      ? ("brain " + (pantheon.minds ? "ON" : "off") + " · " + pantheon.clock.phase + " · hour " + pantheon.clock.hour +
         " · " + (quality === "high" ? "quality high" : "quality fast" + (qualityNoted ? " (auto, Q to restore)" : "")))
      : "brain —";
  }
  if (hud.compass){
    const yaw = ((theta * 180 / Math.PI) % 360 + 360) % 360;
    const dirs = [["N", 0], ["E", 90], ["S", 180], ["W", 270]];
    hud.compass.innerHTML = dirs.map(([l, dd]) => {
      let rel = (dd - yaw + 360) % 360; if (rel > 180) rel -= 360;
      return `<span style="${Math.abs(rel) < 20 ? "color:var(--accent)" : ""}">${l}</span>`;
    }).join(" ");
  }

  const mv = keys.w || keys.s || keys.a || keys.d || keys.ArrowUp || keys.ArrowDown || keys.ArrowLeft || keys.ArrowRight;
  const stepCycle=mv?Math.sin(t*7.2):0;
  avatar.position.y = mv ? Math.abs(Math.sin(t*7.2))*0.045 : 0;
  avatar.userData.arms.forEach((arm,i)=>{arm.rotation.x+=(stepCycle*(i===0?0.35:-0.35)-arm.rotation.x)*0.2;});
  avatar.userData.legs.forEach((leg,i)=>{leg.rotation.x+=(stepCycle*(i===0?-0.4:0.4)-leg.rotation.x)*0.2;});

  cameraFromAvatar(dt);
  updateFaceBubbles(now);
  adaptQuality(dt);
  if (atmos && avatar) atmos.update(avatar.position, darkness);
  if (gpuPipe && quality === "high"){
    gpuPipe.setBloom(0.12 + darkness * 0.3);
    gpuPipe.render();
  } else if (composer && quality === "high"){
    if (bloomPass) bloomPass.strength = 0.12 + darkness * 0.3;
    composer.render(dt);
  } else renderer.render(scene, camera);
}

/* If frames stay slow for a few seconds, drop post-processing (Q brings it back). */
let slowFor = 0, qualityNoted = false;
function adaptQuality(dt){
  if (quality !== "high" || (!composer && !gpuPipe)) return;
  slowFor = dt > 1 / 28 ? slowFor + dt : Math.max(0, slowFor - dt * 2);
  if (slowFor > 4){ quality = "fast"; slowFor = 0; qualityNoted = true; }
}

/* Post-processing: ground-truth ambient occlusion (contact shadows in corners, under cars and
 * eaves), bloom for lamps, windows and headlights, then tone mapping and sRGB output. The
 * composer's targets are multisampled, so edges stay anti-aliased. Q toggles it off for
 * slower machines. */
function buildComposer(w, h){
  const target = new THREE.WebGLRenderTarget(w, h, {type: THREE.HalfFloatType, samples: 4});
  composer = new EffectComposer(renderer, target);
  composer.addPass(new RenderPass(scene, camera));
  gtaoPass = new GTAOPass(scene, camera, w, h);
  gtaoPass.updateGtaoMaterial({radius: 0.6, distanceExponent: 1.4, thickness: 1.2, scale: 1.1, samples: 12});
  gtaoPass.updatePdMaterial({lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6, rings: 2, samples: 12});
  gtaoPass.blendIntensity = 0.85;
  composer.addPass(gtaoPass);
  bloomPass = new UnrealBloomPass(new THREE.Vector2(w, h), 0.25, 0.5, 0.86);
  composer.addPass(bloomPass);
  composer.addPass(new OutputPass());
}

function resize(){
  if (!renderer || !rootEl) return;
  const w = rootEl.clientWidth, h = rootEl.clientHeight || 600;
  camera.aspect = w / h; camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  if (composer){ composer.setSize(w, h); if (gtaoPass) gtaoPass.setSize(w, h); }
}

/* ---------------------------------------------------------------- lifecycle */
export function mount(ctx){
  cameraReady = false;
  theta = 0; phi = 0.5; radius = 9; keys = {};
  rootEl = document.createElement("div");
  rootEl.className = "w3d-wrap";
  ctx.root.innerHTML = "";
  ctx.root.appendChild(rootEl);

  disposed = false;
  boot(ctx);
}

async function boot(ctx){
  G = await GPU.loadGPU();
  if (disposed) return;
  if (G) {
    try { buildWorld(); renderer = await GPU.createRenderer(G); }
    catch (e) { console.warn("WebGPU renderer refused; using WebGL2", e); G = null; renderer = null; }
  }
  if (disposed) { if (renderer) renderer.dispose(); return; }
  if (!renderer) { buildWorld(); renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: "high-performance"}); }
  // WebGPU takes native resolution (AO and bloom still run per pixel, but on compute-class hardware)
  renderer.setPixelRatio(Math.min(G ? 2 : 1.5, window.devicePixelRatio || 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.75;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  try {
    if (G) { gpuPipe = GPU.buildPipeline(G, renderer, scene, camera); atmos = GPU.createAtmosphere(G, renderer, scene); }
    else buildComposer(rootEl.clientWidth || 800, rootEl.clientHeight || 600);
  } catch (e) { console.warn("post-processing unavailable; rendering directly", e); composer = null; gpuPipe = null; }
  rootEl.appendChild(renderer.domElement);
  buildHud();
  bindInput();
  resize();
  window.addEventListener("resize", resize);
  loadColony();
  loadPantheon();
  window.__w3d = { pos: () => avatar ? [avatar.position.x, avatar.position.z] : null,
                   keys: () => Object.keys(keys).filter(k => keys[k]),
                   step: (dt) => step(dt),
                   beings: () => [...beings.keys()],
                   bodies: () => [...beings.entries()].map(([name,b])=>({name,x:b.group.position.x,z:b.group.position.z,activity:b.p&&b.p.activity,meshes:b.group.children.length})),
                   agents: () => colonyAgents().length,
                   workstations: () => [...workstations.values()].map(w=>{const a=stationArtifact(w.name);return {name:w.name,home:w.homeId,x:w.group.position.x,z:w.group.position.z,artifact:a&&a.title,latestTool:a&&a.content&&a.content.tools&&a.content.tools[0]&&a.content.tools[0].name};}),
                   places: () => placesList().map(p=>({id:p.id,name:p.name,kind:p.kind,dynamic:!!p.dynamic,x:p.x,z:p.z})),
                   pantheon: () => pantheon ? {phase: pantheon.clock.phase, hour: pantheon.clock.hour, minds: pantheon.minds, n: (pantheon.agents || []).length, generatedPlaces:(pantheon.places||[]).filter(p=>p.dynamic).length, artifacts:(pantheon.artifacts||[]).length} : null,
                   voice: () => ({name:faceVoice.name, recording:!!faceVoice.capture, busy:faceVoice.busy, bubbles:faceBubbles.map(b=>({name:b.name,text:b.el.querySelector('.w3d-speech-text')?.textContent,voice:b.el.querySelector('.w3d-speech-head span')?.textContent}))}),
                   bubble: (name,text,voice) => addFaceBubble(name,text,voice),
                   sync: () => syncAgents(),
                   near: () => near ? {kind: near.kind, label: near.label} : null,
                   nearOf: () => { const it = nearestInteractable(); return it ? {kind: it.kind, label: it.label, name: it.mind || null} : null; },
                   nearCI: () => nearestBeing(),
                   promptText: () => promptText(),
                   camera: () => ({theta,phi,radius,position:camera?[camera.position.x,camera.position.y,camera.position.z]:null}),
                   open: (k, p) => openOverlay(k, p || []),
                   close: () => closeOverlay(),
                   hour: (h) => { hourOverride = (h == null ? null : Number(h)); },
                   view: (t, ph, r) => { theta = t; phi = ph; radius = r; },
                   drawCalls: () => renderer ? renderer.info.render.calls : null,
                   city: () => city ? {cars: city.cars.length, lamps: city.lampPositions.length, children: city.group.children.length} : null,
                   quality: (q) => { if (q) quality = q; return {quality, composer: !!composer || !!gpuPipe}; },
                   atmosphere: (on) => { if (atmos) atmos.enable(on); },
                   backend: () => ({renderer: G ? "webgpu" : "webgl2", atmosphere: atmos ? atmos.count : 0,
                                    pixelRatio: renderer ? renderer.getPixelRatio() : null, gpu: G ? G.limits : null}),
                   collides: (x, z) => { const [cx, cz] = resolveCollisions(x, z); return Math.hypot(cx - x, cz - z) > 1e-6; },
                   colliders: () => colliders.length,
                   set: (x, z) => { if (avatar){ avatar.position.set(x, 0, z); near = nearestInteractable(); } } };
  animate();
}

export function update(ctx){
  if (!scene) return;
  loadPantheon();
  syncAgents();
}

export function unmount(ctx){
  disposed = true;
  clearFaceVoice();
  cancelAnimationFrame(raf);
  window.removeEventListener("resize", resize);
  closeOverlay();
  if (renderer){ renderer.dispose(); renderer = null; }
  if (rootEl && rootEl.parentNode) rootEl.parentNode.removeChild(rootEl);
  beings.clear(); interactables = []; pBuildings.clear(); worldAssets.clear();
  talkBubbles.forEach(b => { try { scene.remove(b.sprite); } catch (e) {} });
  talkBubbles = [];
  for(const station of workstations.values())station.texture.dispose();
  workstations.clear();
  scene = null; camera = null; avatar = null; rootEl = null; pantheon = null;
  sunLight = null; moonMesh = null; hemi = null; sky = null;
  if (envRT){ envRT.dispose(); envRT = null; }
  if (envGen){ envGen.dispose(); envGen = null; }
  envSky = null; envScene = null; lamps = []; windowMats = []; colliders = []; layout = null;
  if (city){ city.dispose(); city = null; } cityKey = ""; lampPool = []; lastThought = new Map();
  if (composer){ composer.dispose(); composer = null; } gtaoPass = null; bloomPass = null;
  if (atmos){ atmos.dispose(); atmos = null; } if (gpuPipe){ gpuPipe.dispose(); gpuPipe = null; } G = null;
  hud = {};
}
