/* city — the town plan rendered: streets, highway, plaza, houses, lamps, trees and traffic.
 *
 * Everything here is drawn from the server's plan (cityplan.py via /api/pantheon `layout`),
 * the same plan the residents navigate and the visitor collides with. Surfaces use
 * procedural canvas textures (no downloads); lamps, windows and car lights are emissive so
 * the bloom pass picks them up at night. Traffic is ambient: cars follow their lanes and
 * never stand in for a resident.
 */
import * as THREE from "three";
import { mergeGeometries } from "/api/static/vendor/jsm/utils/BufferGeometryUtils.js";

/* Collapse every static mesh under `root` into one mesh per material, in root's own frame.
 * A town of thousands of dashes, windows and kerbs becomes a few dozen draw calls. Meshes
 * marked userData.dynamic (and anything that is not a mesh, e.g. labels and lights) stay. */
export function mergeStatic(root){
  root.updateMatrixWorld(true);
  const inv = new THREE.Matrix4().copy(root.matrixWorld).invert();
  const byMat = new Map(), drop = [];
  root.traverse(o => {
    if (!o.isMesh || o === root || o.userData.dynamic) return;
    for (let p = o.parent; p && p !== root; p = p.parent) if (p.userData.dynamic) return;
    const g = (o.geometry.index ? o.geometry.toNonIndexed() : o.geometry.clone());
    for (const name of Object.keys(g.attributes)) if (!["position", "normal", "uv"].includes(name)) g.deleteAttribute(name);
    if (!g.attributes.uv) g.setAttribute("uv", new THREE.Float32BufferAttribute(new Float32Array(g.attributes.position.count * 2), 2));
    g.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld));
    const key = o.material.uuid;
    if (!byMat.has(key)) byMat.set(key, {material: o.material, geos: [], cast: false});
    const entry = byMat.get(key); entry.geos.push(g); entry.cast = entry.cast || o.castShadow;
    drop.push(o);
  });
  for (const o of drop) o.parent.remove(o);
  for (const {material, geos, cast} of byMat.values()){
    const merged = mergeGeometries(geos, false);
    geos.forEach(g => g.dispose());
    if (!merged) continue;
    const m = new THREE.Mesh(merged, material);
    m.castShadow = cast; m.receiveShadow = true;
    root.add(m);
  }
  // emptied sub-groups are left in place (they may carry userData for interaction)
  return root;
}

/* ---------------------------------------------------------------- textures */
const texCache = new Map();
function canvasTex(key, size, draw, repeat){
  if (!texCache.has(key)){
    const c = document.createElement("canvas"); c.width = c.height = size;
    draw(c.getContext("2d"), size);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
    texCache.set(key, t);
  }
  const t = texCache.get(key).clone(); t.needsUpdate = true;
  if (repeat) t.repeat.set(repeat[0], repeat[1]);
  return t;
}
function rng(seed){ return () => ((seed = (seed * 16807) % 2147483647) / 2147483647); }
function speckle(g, size, base, spread, n, seed){
  g.fillStyle = base; g.fillRect(0, 0, size, size);
  const r = rng(seed);
  for (let i = 0; i < n; i++){
    const v = Math.floor((r() - 0.5) * spread);
    g.fillStyle = `rgba(${v > 0 ? 255 : 0},${v > 0 ? 255 : 0},${v > 0 ? 255 : 0},${Math.abs(v) / 255})`;
    g.fillRect(r() * size, r() * size, 1 + r() * 2, 1 + r() * 2);
  }
}
const TEX = {
  asphalt: (rep) => canvasTex("asphalt", 256, (g, s) => {
    speckle(g, s, "#34383b", 90, 9000, 11);
    const r = rng(5); g.strokeStyle = "rgba(20,22,24,0.5)"; g.lineWidth = 1;
    for (let i = 0; i < 6; i++){ g.beginPath(); let x = r() * s, y = r() * s; g.moveTo(x, y);
      for (let k = 0; k < 6; k++){ x += (r() - 0.5) * 40; y += (r() - 0.5) * 40; g.lineTo(x, y); } g.stroke(); }
  }, rep),
  paving: (rep) => canvasTex("paving", 256, (g, s) => {
    speckle(g, s, "#8c877c", 50, 4000, 3);
    g.strokeStyle = "rgba(60,56,50,0.55)"; g.lineWidth = 2;
    for (let i = 0; i <= 8; i++){ g.beginPath(); g.moveTo(0, i * s / 8); g.lineTo(s, i * s / 8); g.stroke(); }
    for (let row = 0; row < 8; row++) for (let i = 0; i <= 4; i++){
      const x = (i + (row % 2) * 0.5) * s / 4; g.beginPath(); g.moveTo(x, row * s / 8); g.lineTo(x, (row + 1) * s / 8); g.stroke(); }
  }, rep),
  sidewalk: (rep) => canvasTex("sidewalk", 128, (g, s) => {
    speckle(g, s, "#77746c", 40, 1500, 9);
    g.strokeStyle = "rgba(50,48,44,0.6)"; g.lineWidth = 2; g.strokeRect(1, 1, s - 2, s - 2);
  }, rep),
  plaster: (rep, tint) => canvasTex("plaster-" + tint, 128, (g, s) => speckle(g, s, tint, 26, 2500, 17), rep),
  roof: (rep) => canvasTex("roof", 128, (g, s) => {
    g.fillStyle = "#5d3a2e"; g.fillRect(0, 0, s, s);
    for (let row = 0; row < 8; row++) for (let i = 0; i < 8; i++){
      const r = rng(row * 31 + i * 7 + 1)(); g.fillStyle = `hsl(${12 + r * 10},${32 + r * 12}%,${22 + r * 10}%)`;
      g.fillRect((i + (row % 2) * 0.5) * s / 8, row * s / 8, s / 8 - 2, s / 8 - 2);
    }
  }, rep),
  concrete: (rep) => canvasTex("concrete", 128, (g, s) => speckle(g, s, "#9a9890", 34, 2000, 23), rep),
};

/* ---------------------------------------------------------------- strips along polylines */
function strip(points, width, offset, y, material, extend = 0){
  // One quad per segment, extended past its ends so square-ring corners close.
  const group = new THREE.Group();
  for (let i = 0; i < points.length - 1; i++){
    const [ax, az] = points[i], [bx, bz] = points[i + 1];
    const L = Math.hypot(bx - ax, bz - az); if (!L) continue;
    const ux = (bx - ax) / L, uz = (bz - az) / L, nx = -uz, nz = ux;
    const len = L + extend * 2;
    const geo = new THREE.PlaneGeometry(width, len);
    if (material.map){
      const uv = geo.attributes.uv;
      for (let k = 0; k < uv.count; k++) uv.setXY(k, uv.getX(k) * width / 4, uv.getY(k) * len / 4);
    }
    const m = new THREE.Mesh(geo, material);
    m.rotation.set(-Math.PI / 2, 0, 0); m.rotateZ(Math.atan2(ux, uz));   // plane's length onto the segment
    m.position.set((ax + bx) / 2 + nx * offset, y, (az + bz) / 2 + nz * offset);
    m.receiveShadow = true;
    group.add(m);
  }
  return group;
}

function dashes(points, offset, y, mat, dash = 2.4, gap = 3.2, w = 0.13){
  const group = new THREE.Group();
  for (let i = 0; i < points.length - 1; i++){
    const [ax, az] = points[i], [bx, bz] = points[i + 1];
    const L = Math.hypot(bx - ax, bz - az); if (!L) continue;
    const ux = (bx - ax) / L, uz = (bz - az) / L, nx = -uz, nz = ux;
    for (let d = gap / 2; d < L - dash; d += dash + gap){
      const m = new THREE.Mesh(new THREE.PlaneGeometry(w, dash), mat);
      m.rotation.set(-Math.PI / 2, 0, 0); m.rotateZ(Math.atan2(ux, uz));
      m.position.set(ax + ux * (d + dash / 2) + nx * offset, y, az + uz * (d + dash / 2) + nz * offset);
      group.add(m);
    }
  }
  return group;
}

function rail(points, offset, height, thick, mat, y = 0){
  const group = new THREE.Group();
  for (let i = 0; i < points.length - 1; i++){
    const [ax, az] = points[i], [bx, bz] = points[i + 1];
    const L = Math.hypot(bx - ax, bz - az); if (!L) continue;
    const ux = (bx - ax) / L, uz = (bz - az) / L, nx = -uz, nz = ux;
    const m = new THREE.Mesh(new THREE.BoxGeometry(thick, height, L + thick), mat);
    m.rotation.y = Math.atan2(ux, uz);
    m.position.set((ax + bx) / 2 + nx * offset, y + height / 2, (az + bz) / 2 + nz * offset);
    m.castShadow = m.receiveShadow = true;
    group.add(m);
  }
  return group;
}

function offsetPolyline(points, off){
  // Mitred offset of a polyline (closed when first == last).
  const closed = points.length > 2 && points[0][0] === points.at(-1)[0] && points[0][1] === points.at(-1)[1];
  const pts = closed ? points.slice(0, -1) : points;
  const out = pts.map((p, i) => {
    const prev = pts[(i - 1 + pts.length) % pts.length], next = pts[(i + 1) % pts.length];
    const segs = [];
    if (closed || i > 0) segs.push([p[0] - prev[0], p[1] - prev[1]]);
    if (closed || i < pts.length - 1) segs.push([next[0] - p[0], next[1] - p[1]]);
    let nx = 0, nz = 0;
    for (const [dx, dz] of segs){ const L = Math.hypot(dx, dz) || 1; nx += -dz / L; nz += dx / L; }
    const nl = Math.hypot(nx, nz) || 1; nx /= nl; nz /= nl;
    const [dx, dz] = segs[0]; const L = Math.hypot(dx, dz) || 1;
    const cos = Math.max(0.35, nx * (-dz / L) + nz * (dx / L));
    return [p[0] + nx * off / cos, p[1] + nz * off / cos];
  });
  if (closed) out.push(out[0]);
  return out;
}

/* ---------------------------------------------------------------- roads */
function buildRoads(lay, group){
  const asphaltMat = new THREE.MeshStandardMaterial({color: 0xffffff, map: TEX.asphalt([1, 1]), roughness: 0.9,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2});
  const walkMat = new THREE.MeshStandardMaterial({color: 0xffffff, map: TEX.sidewalk([1, 1]), roughness: 0.95,
    polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1});
  const white = new THREE.MeshStandardMaterial({color: 0xdedbd2, roughness: 0.7, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4});
  const yellow = new THREE.MeshStandardMaterial({color: 0xd7b04a, roughness: 0.7, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4});
  const kerb = new THREE.MeshStandardMaterial({color: 0x8d8a82, roughness: 0.9});
  const barrier = new THREE.MeshStandardMaterial({color: 0xffffff, map: TEX.concrete([1, 1]), roughness: 0.85});
  const steel = new THREE.MeshStandardMaterial({color: 0xb9bec0, metalness: 0.75, roughness: 0.35});
  for (const r of lay.roads){
    const pts = r.points, half = r.width / 2;
    if (r.kind === "highway"){
      group.add(strip(pts, r.width, 0, 0.03, asphaltMat, 0));
      group.add(rail(pts, 0, 0.82, 0.55, barrier));                       // median barrier
      for (const side of [-1, 1]){
        group.add(rail(pts, side * (half + 0.2), 0.12, 0.08, steel, 0.55)); // guardrail beam
        group.add(dashes(pts, side * (half - 0.35), 0.045, white, 1e3, 0.01, 0.16)); // edge line
        group.add(dashes(pts, side * 4.3, 0.045, white));                    // lane divider
        group.add(dashes(pts, side * 1.0, 0.045, yellow, 1e3, 0.01, 0.14));  // inner edge
      }
      continue;
    }
    for (const side of [-1, 1]){
      group.add(strip(pts, 2.2, side * (half + 1.1), 0.025, walkMat, r.kind === "lane" ? 0 : half + 2.2));
      group.add(rail(pts, side * (half + 0.06), 0.08, 0.14, kerb, 0.0));
    }
    group.add(strip(pts, r.width, 0, 0.035, asphaltMat, r.closed ? half : 0));
    if (r.kind === "boulevard"){
      for (const s of [-0.12, 0.12]) group.add(dashes(pts, s, 0.045, yellow, 1e3, 0.01, 0.1));
      for (const s of [-1, 1]) group.add(dashes(pts, s * half / 2, 0.045, white));
    } else if (r.kind !== "lane"){
      group.add(dashes(pts, 0, 0.045, r.kind === "avenue" ? yellow : white));
    }
  }
  // zebra crossings where the avenues meet each ring
  const zebra = new THREE.MeshStandardMaterial({color: 0xe8e5dc, roughness: 0.7, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4});
  const ave = lay.roads.filter(r => r.kind === "avenue"), rings = lay.roads.filter(r => r.kind === "boulevard" || r.kind === "street");
  for (const a of ave){
    const [ax, az] = a.points[0], [bx, bz] = a.points[1], L = Math.hypot(bx - ax, bz - az), ux = (bx - ax) / L, uz = (bz - az) / L;
    for (const ring of rings){
      const ringHalf = Math.abs(ring.points[0][0]);
      for (const sgn of [-1, 1]){
        const d = ringHalf - Math.hypot(ax, az) + sgn * (ring.width / 2 + 1.6);
        if (d < 0 || d > L) continue;
        for (let k = -3; k <= 3; k++){
          const m = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 2.6), zebra);
          m.rotation.set(-Math.PI / 2, 0, 0); m.rotateZ(Math.atan2(ux, uz));
          m.position.set(ax + ux * d + uz * k * 0.9, 0.047, az + uz * d - ux * k * 0.9);
          group.add(m);
        }
      }
    }
  }
  // the paved civic plaza
  const px = lay.plaza.x, pz = lay.plaza.z;
  const plaza = new THREE.Mesh(new THREE.PlaneGeometry(px * 2, pz * 2),
    new THREE.MeshStandardMaterial({color: 0xffffff, map: TEX.paving([px / 3, pz / 3]), roughness: 0.92,
      polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1}));
  plaza.rotation.x = -Math.PI / 2; plaza.position.y = 0.02; plaza.receiveShadow = true;
  group.add(plaza);
}

/* ---------------------------------------------------------------- houses */
const FACING_YAW = {"+z": 0, "-z": Math.PI, "+x": Math.PI / 2, "-x": -Math.PI / 2};
const PLASTER = ["#c9bea8", "#b9b2a2", "#cbb79a", "#aeb3ad", "#c2a990", "#bfb8aa"];

function nameplate(text){
  const c = document.createElement("canvas"); c.width = 512; c.height = 96;
  const g = c.getContext("2d"); g.fillStyle = "#2b2f30"; g.fillRect(0, 0, 512, 96);
  g.fillStyle = "#e8e2d4"; g.font = "600 46px ui-sans-serif, system-ui"; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(text, 256, 50);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return new THREE.Mesh(new THREE.PlaneGeometry(1.4, 0.26), new THREE.MeshStandardMaterial({map: t, roughness: 0.6}));
}

function buildHouse(h, windowMats, lampMats){
  const g = new THREE.Group();
  const w = h.width, d = h.depth, wallH = 3.0;
  const r = rng(h.seed || 7);
  const plaster = new THREE.MeshStandardMaterial({color: 0xffffff, map: TEX.plaster([2, 1], PLASTER[(h.seed || 0) % PLASTER.length]), roughness: 0.92});
  const trim = new THREE.MeshStandardMaterial({color: 0xe9e4d8, roughness: 0.7});
  const roofMat = new THREE.MeshStandardMaterial({color: 0xffffff, map: TEX.roof([3, 2]), roughness: 0.85});
  const glass = new THREE.MeshStandardMaterial({color: 0x3c4c52, roughness: 0.08, metalness: 0.2, emissive: 0xffc27a, emissiveIntensity: 0});
  windowMats.push(glass);
  const wall = (W, H, D, x, y, z) => { const m = new THREE.Mesh(new THREE.BoxGeometry(W, H, D), plaster); m.position.set(x, y, z); g.add(m); };
  const T = 0.22, door = 0.58;
  wall(T, wallH, d, -w / 2 + T / 2, wallH / 2, 0); wall(T, wallH, d, w / 2 - T / 2, wallH / 2, 0);
  wall(w, wallH, T, 0, wallH / 2, -d / 2 + T / 2);
  wall(w / 2 - door, wallH, T, -(w / 4 + door / 2), wallH / 2, d / 2 - T / 2);
  wall(w / 2 - door, wallH, T, (w / 4 + door / 2), wallH / 2, d / 2 - T / 2);
  wall(door * 2, wallH - 2.25, T, 0, 2.25 + (wallH - 2.25) / 2, d / 2 - T / 2);
  const floor = new THREE.Mesh(new THREE.BoxGeometry(w, 0.12, d), new THREE.MeshStandardMaterial({color: 0x7a5f45, roughness: 0.8}));
  floor.position.y = 0.06; g.add(floor);
  // windows: front pair, one each side, two at the back
  const win = (x, z, rotY) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(1.05, 1.15, 0.08), glass); m.position.set(x, 1.65, z); m.rotation.y = rotY; g.add(m);
    const sill = new THREE.Mesh(new THREE.BoxGeometry(1.25, 0.08, 0.2), trim); sill.position.set(x, 1.04, z); sill.rotation.y = rotY; g.add(sill);
  };
  win(-w / 4 - 0.4, d / 2 + 0.01, 0); win(w / 4 + 0.4, d / 2 + 0.01, 0);
  win(-w / 2 - 0.01, 0, Math.PI / 2); win(w / 2 + 0.01, 0, Math.PI / 2);
  win(-w / 4, -d / 2 - 0.01, 0); win(w / 4, -d / 2 - 0.01, 0);
  // gabled roof over the long side, with eaves
  const pitch = 1.7 + r() * 0.5;
  const shape = new THREE.Shape(); shape.moveTo(-w / 2 - 0.5, 0); shape.lineTo(w / 2 + 0.5, 0); shape.lineTo(0, pitch); shape.closePath();
  const roofGeo = new THREE.ExtrudeGeometry(shape, {depth: d + 0.8, bevelEnabled: false});
  roofGeo.translate(0, 0, -(d + 0.8) / 2);
  const roof = new THREE.Mesh(roofGeo, roofMat); roof.position.y = wallH; g.add(roof);
  const chimney = new THREE.Mesh(new THREE.BoxGeometry(0.55, 1.6, 0.55), new THREE.MeshStandardMaterial({color: 0x6e4c3d, roughness: 0.9}));
  chimney.position.set(w / 4, wallH + pitch * 0.7, -d / 6); g.add(chimney);
  // front door, porch canopy and lamp
  const doorMesh = new THREE.Mesh(new THREE.BoxGeometry(door * 2 - 0.1, 2.15, 0.06),
    new THREE.MeshStandardMaterial({color: [0x3f5a4e, 0x6a3b32, 0x2f4058, 0x5b4a33][(h.seed || 0) % 4], roughness: 0.6}));
  doorMesh.position.set(-door + 0.05, 1.1, d / 2 + 0.02); doorMesh.rotation.y = -1.1; doorMesh.translateX(door - 0.05); g.add(doorMesh);
  const canopy = new THREE.Mesh(new THREE.BoxGeometry(2.2, 0.12, 1.1), trim); canopy.position.set(0, 2.45, d / 2 + 0.5); g.add(canopy);
  const lampMat = new THREE.MeshStandardMaterial({color: 0xfff1d0, emissive: 0xffc77a, emissiveIntensity: 0.1});
  lampMats.push(lampMat);
  const porchLamp = new THREE.Mesh(new THREE.SphereGeometry(0.11, 10, 8), lampMat); porchLamp.position.set(0.9, 2.2, d / 2 + 0.12); g.add(porchLamp);
  // yard: lawn, path, hedge, nameplate
  const lawn = new THREE.Mesh(new THREE.PlaneGeometry(w + 4, d + 5), new THREE.MeshStandardMaterial({color: 0x56703f, roughness: 1}));
  lawn.rotation.x = -Math.PI / 2; lawn.position.set(0, 0.012, 0.6); g.add(lawn);
  const path = new THREE.Mesh(new THREE.PlaneGeometry(1.2, 2.6), new THREE.MeshStandardMaterial({color: 0xffffff, map: TEX.paving([0.5, 1]), roughness: 0.9}));
  path.rotation.x = -Math.PI / 2; path.position.set(0, 0.02, d / 2 + 1.5); g.add(path);
  const hedgeMat = new THREE.MeshStandardMaterial({color: 0x34502f, roughness: 1});
  for (const side of [-1, 1]){
    const hedge = new THREE.Mesh(new THREE.BoxGeometry((w + 4) / 2 - 1, 0.8, 0.6), hedgeMat);
    hedge.position.set(side * ((w + 4) / 4 + 0.5), 0.4, d / 2 + 2.8); g.add(hedge);
  }
  const plate = nameplate(h.owner); plate.position.set(-1.6, 1.0, d / 2 + 2.8 + 0.31); g.add(plate);
  g.position.set(h.x, 0, h.z); g.rotation.y = FACING_YAW[h.facing] || 0;
  g.userData = {placeId: h.id, label: null, width: w, depth: d, buildingH: wallH + pitch};
  return g;
}

/* ---------------------------------------------------------------- lamps & trees */
function buildLamp(l, lampMats){
  const g = new THREE.Group();
  const metal = new THREE.MeshStandardMaterial({color: 0x3d4244, metalness: 0.6, roughness: 0.45});
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.09, 5.2, 8), metal); pole.position.y = 2.6; g.add(pole);
  const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.05, 1.3, 6), metal);
  arm.rotation.z = Math.PI / 2; arm.position.set(0.6, 5.05, 0); g.add(arm);
  const mat = new THREE.MeshStandardMaterial({color: 0xfff3da, emissive: 0xffd9a0, emissiveIntensity: 0.15, roughness: 0.4});
  lampMats.push(mat);
  const head = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.12, 0.26), mat); head.position.set(1.2, 4.98, 0); g.add(head);
  // the arm (local +x) reaches over the road: yaw is the heading from the lamp to the road
  g.position.set(l.x, 0, l.z); g.rotation.y = Math.atan2(-Math.cos(l.yaw || 0), Math.sin(l.yaw || 0));
  g.userData.lightAt = new THREE.Vector3(l.x, 4.8, l.z).add(new THREE.Vector3(1.2, 0, 0).applyAxisAngle(new THREE.Vector3(0, 1, 0), g.rotation.y));
  return g;
}

function buildTree(t, i){
  const trunkMat = new THREE.MeshStandardMaterial({color: 0x51463a, roughness: 0.98});
  const leaf = [0x3b5236, 0x445a38, 0x4d5d3c, 0x3a5240][i % 4];
  const leafMat = new THREE.MeshStandardMaterial({color: leaf, roughness: 0.95, flatShading: true});
  const r = rng(t.seed || i + 1);
  const g = new THREE.Group();
  const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.22, t.h * 0.6, 8), trunkMat);
  trunk.position.y = t.h * 0.3; g.add(trunk);
  for (let j = 0; j < 5; j++){
    const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(0.9 + r() * 0.5, 1), leafMat);
    crown.position.set((r() - 0.5) * 1.2, t.h * 0.62 + r() * 1.1, (r() - 0.5) * 1.2);
    crown.scale.set(1, 0.8 + r() * 0.3, 1); g.add(crown);
  }
  g.position.set(t.x, 0, t.z); g.rotation.y = r() * Math.PI * 2;
  return g;
}

/* ---------------------------------------------------------------- traffic */
export function carModel(color){
  const g = new THREE.Group();
  const paint = new THREE.MeshPhysicalMaterial({color, metalness: 0.6, roughness: 0.32, clearcoat: 1, clearcoatRoughness: 0.08});
  const glass = new THREE.MeshStandardMaterial({color: 0x1d2629, roughness: 0.05, metalness: 0.4});
  const rubber = new THREE.MeshStandardMaterial({color: 0x161718, roughness: 0.85});
  const chrome = new THREE.MeshStandardMaterial({color: 0xcfd3d4, metalness: 0.9, roughness: 0.2});
  const side = new THREE.Shape();      // side profile, x along the car (+x = front), y up
  side.moveTo(-2.15, 0.32); side.lineTo(2.15, 0.32); side.quadraticCurveTo(2.3, 0.36, 2.25, 0.72);
  side.lineTo(1.25, 0.86); side.lineTo(0.55, 1.36); side.lineTo(-1.15, 1.36); side.lineTo(-1.85, 0.92);
  side.lineTo(-2.2, 0.86); side.quadraticCurveTo(-2.3, 0.5, -2.15, 0.32);
  const body = new THREE.Mesh(new THREE.ExtrudeGeometry(side, {depth: 1.72, bevelEnabled: true, bevelSize: 0.06, bevelThickness: 0.06, bevelSegments: 2}), paint);
  body.geometry.translate(0, 0, -0.86); g.add(body);
  const cabin = new THREE.Shape();
  cabin.moveTo(1.2, 0.9); cabin.lineTo(0.55, 1.32); cabin.lineTo(-1.1, 1.32); cabin.lineTo(-1.75, 0.94); cabin.closePath();
  const win = new THREE.Mesh(new THREE.ExtrudeGeometry(cabin, {depth: 1.76, bevelEnabled: false}), glass);
  win.geometry.translate(0, 0, -0.88); g.add(win);
  for (const x of [-1.35, 1.35]) for (const z of [-0.86, 0.86]){
    const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.24, 16), rubber);
    wheel.rotation.x = Math.PI / 2; wheel.position.set(x, 0.34, z); g.add(wheel);
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 0.26, 12), chrome);
    hub.rotation.x = Math.PI / 2; hub.position.set(x, 0.34, z); g.add(hub);
  }
  const head = new THREE.MeshStandardMaterial({color: 0xfffbe8, emissive: 0xfff2c8, emissiveIntensity: 0.2});
  const tail = new THREE.MeshStandardMaterial({color: 0x5a0d0d, emissive: 0xff2a1a, emissiveIntensity: 0.25});
  for (const z of [-0.6, 0.6]){
    const hl = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.12, 0.34), head); hl.position.set(2.27, 0.62, z); g.add(hl);
    const tl = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.12, 0.3), tail); tl.position.set(-2.25, 0.74, z); g.add(tl);
  }
  g.traverse(o => { if (o.isMesh){ o.castShadow = true; } });
  g.userData.lights = [head, tail];
  return g;
}

function lanePath(points){
  const segs = []; let total = 0;
  for (let i = 0; i < points.length - 1; i++){
    const L = Math.hypot(points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]);
    segs.push({a: points[i], b: points[i + 1], L, at: total}); total += L;
  }
  return {segs, total};
}
function lanePoint(lane, s){
  s = ((s % lane.total) + lane.total) % lane.total;
  for (const seg of lane.segs){
    if (s <= seg.at + seg.L){
      const t = seg.L ? (s - seg.at) / seg.L : 0;
      return {x: seg.a[0] + (seg.b[0] - seg.a[0]) * t, z: seg.a[1] + (seg.b[1] - seg.a[1]) * t,
              yaw: Math.atan2(seg.b[1] - seg.a[1], seg.b[0] - seg.a[0])};
    }
  }
  return {x: lane.segs[0].a[0], z: lane.segs[0].a[1], yaw: 0};
}

const CAR_COLORS = [0x1d3557, 0x8a1c1c, 0xd9d6cf, 0x2b2d2f, 0x4a5a3c, 0x9aa3a8, 0x6b4f2a, 0x24464f, 0xb7b1a3];

function buildTraffic(lay, group){
  const cars = [];
  const plan = [["highway", [[-1, 6.0], [-1, 2.6], [1, 2.6], [1, 6.0]], 7, 15],
                ["boulevard", [[-1, 2], [1, 2]], 4, 9], ["residential", [[-1, 1.5], [1, 1.5]], 2, 7]];
  let n = 0;
  for (const [id, lanes, perLane, speed] of plan){
    const road = lay.roads.find(r => r.id === id); if (!road) continue;
    for (const [dir, off] of lanes){
      // Right-hand traffic: offset to the right of the direction of travel.
      const pts = dir > 0 ? road.points : road.points.slice().reverse();
      const lane = lanePath(offsetPolyline(pts, -off));
      for (let k = 0; k < perLane; k++){
        const car = carModel(CAR_COLORS[n++ % CAR_COLORS.length]);
        group.add(car);
        cars.push({car, lane, s: lane.total * (k + rng(n * 13)() * 0.5) / perLane, speed: speed * (0.85 + rng(n * 7)() * 0.3)});
      }
    }
  }
  return cars;
}

/* ---------------------------------------------------------------- the city */
export function buildCity(lay){
  const group = new THREE.Group(); group.name = "city";
  const windowMats = [], lampMats = [], lampPositions = [];
  buildRoads(lay, group);
  for (const h of lay.houses || []) group.add(buildHouse(h, windowMats, lampMats));
  for (const l of lay.lamps || []){ const g = buildLamp(l, lampMats); lampPositions.push(g.userData.lightAt); group.add(g); }
  (lay.trees || []).forEach((t, i) => group.add(buildTree(t, i)));
  group.traverse(o => { if (o.isMesh && !o.material.transparent){ o.castShadow = o.castShadow || o.position.y > 0.3; o.receiveShadow = true; } });
  // flat road markings never cast shadows; everything else keeps its flag through the merge
  mergeStatic(group);
  const cars = buildTraffic(lay, group);
  for (const c of cars) c.car.userData.dynamic = true;

  function update(dt, dark){
    for (const c of cars){
      c.s += c.speed * dt;
      const p = lanePoint(c.lane, c.s);
      c.car.position.set(p.x, 0, p.z); c.car.rotation.y = -p.yaw;
    }
    for (const m of lampMats) m.emissiveIntensity = 0.15 + dark * 3.2;
    for (const m of windowMats) m.emissiveIntensity = dark * 0.85;
    for (const c of cars){
      const [head, tail] = c.car.userData.lights;
      head.emissiveIntensity = 0.2 + dark * 4; tail.emissiveIntensity = 0.25 + dark * 2.5;
    }
  }
  function dispose(){
    group.traverse(o => { if (o.isMesh){ o.geometry.dispose(); } });
  }
  return {group, update, dispose, lampPositions, windowMats, cars};
}
