/* gpu — the WebGPU path of the 3D world.
 *
 * WebGL2 draws the scene through one command stream and a chain of full-screen passes. WebGPU
 * lets the world use the GPU properly: native-resolution rendering, ground-truth ambient
 * occlusion fed into the lighting itself (not painted over it), temporal anti-aliasing, and
 * compute shaders that run the world's atmosphere — tens of thousands of dust motes and
 * fireflies advected by a 3D noise wind, simulated entirely on the GPU with no CPU involvement.
 *
 * Everything here is optional. `loadGPU()` resolves null where WebGPU is missing, refused, or
 * switched off (`?renderer=webgl`, or localStorage `mist.renderer = "webgl"`), and world3d.js
 * then runs its WebGL2 pipeline unchanged.
 */
export async function loadGPU(){
  try {
    const q = new URLSearchParams(location.search).get("renderer");
    let pref = q; try { pref = pref || localStorage.getItem("mist.renderer"); } catch (e) {}
    if (pref === "webgl" || !navigator.gpu) return null;
    const adapter = await navigator.gpu.requestAdapter({powerPreference: "high-performance"});
    if (!adapter) return null;
    const [T, TSL, sky, ao, bloom, traa] = await Promise.all([
      import("three/webgpu"), import("three/tsl"),
      import("three/addons/objects/SkyMesh.js"),
      import("three/addons/tsl/display/GTAONode.js"),
      import("three/addons/tsl/display/BloomNode.js"),
      import("three/addons/tsl/display/TRAANode.js")]);
    return {T, TSL, SkyMesh: sky.SkyMesh, ao: ao.ao, bloom: bloom.bloom, traa: traa.traa,
            limits: {buffer: adapter.limits.maxBufferSize, invocations: adapter.limits.maxComputeInvocationsPerWorkgroup}};
  } catch (e) {
    console.warn("WebGPU unavailable; using WebGL2", e);
    return null;
  }
}

export async function createRenderer(G){
  const renderer = new G.T.WebGPURenderer({antialias: false, powerPreference: "high-performance"});
  await renderer.init();                       // throws when the device is refused: caller falls back
  return renderer;
}

/* Sky: SkyMesh exposes TSL uniforms where Sky exposed ShaderMaterial uniforms. */
export function makeSky(G){ return new G.SkyMesh(); }
export function setSky(sky, k, v){
  const u = sky[k];
  if (u && u.value && u.value.copy && v && v.isVector3) u.value.copy(v); else if (u) u.value = v;
}
export function getSky(sky, k){ return sky[k].value; }

/* Post-processing: pre-pass (normals + depth + velocity) -> GTAO -> scene pass lit with that
 * occlusion -> temporal AA -> bloom, then the renderer's tone mapping and colour transform. */
export function buildPipeline(G, renderer, scene, camera){
  const {pass, mrt, normalView, velocity, packNormalToRGB, unpackRGBToNormal, sample, screenUV, builtinAOContext, vec4} = G.TSL;
  const rp = new G.T.RenderPipeline(renderer);

  const pre = pass(scene, camera);
  pre.transparent = false;                      // opaque geometry only: no AO from sprites and glass
  pre.setMRT(mrt({output: packNormalToRGB(normalView), velocity}));
  const preNormal = sample(uv => unpackRGBToNormal(pre.getTextureNode().sample(uv)));
  const preDepth = pre.getTextureNode("depth");
  pre.getTexture("output").type = G.T.UnsignedByteType;

  const main = pass(scene, camera);
  const aoNode = G.ao(preDepth, preNormal, camera);
  Object.assign(aoNode, {resolutionScale: 0.5, useTemporalFiltering: true});
  aoNode.radius.value = 0.6; aoNode.thickness.value = 1.2; aoNode.distanceExponent.value = 1.4;
  aoNode.scale.value = 1.1; aoNode.samples.value = 10;
  main.contextNode = builtinAOContext(aoNode.getTextureNode().sample(screenUV).r);

  const aa = G.traa(main, preDepth, pre.getTextureNode("velocity"), camera);
  aa.useSubpixelCorrection = false;
  const glow = G.bloom(aa, 0.12, 0.5, 0.86);
  rp.outputNode = aa.add(glow);

  return {
    render: () => rp.render(),
    setBloom: s => { glow.strength.value = s; },
    dispose: () => { try { aoNode.dispose(); } catch (e) {} rp.dispose && rp.dispose(); },
  };
}

/* Atmosphere simulated on the GPU. State lives in storage buffers; one compute dispatch per
 * frame advects every particle through a 3D noise wind, wraps it around the visitor, and the
 * sprite material reads the same buffer to draw it. By day: dust and pollen. By night:
 * fireflies that wander, bob and pulse. */
export function createAtmosphere(G, renderer, scene, count = 32000){
  const {instancedArray, instanceIndex, Fn, uniform, vec3, float, hash, sin, mx_noise_vec3, time, deltaTime,
         shapeCircle, mix, If} = G.TSL;
  const T = G.T;
  const pos = instancedArray(count, "vec3");
  const center = uniform(new T.Vector3());
  const dark = uniform(0);
  const half = vec3(34, 11, 34);                // the box of air kept around the visitor

  const init = Fn(() => {
    const p = pos.element(instanceIndex);
    p.assign(center.add(vec3(hash(instanceIndex), hash(instanceIndex.add(7)), hash(instanceIndex.add(13)))
      .mul(2).sub(1).mul(half)));
    p.y.assign(hash(instanceIndex.add(13)).mul(14).add(0.2));
  })().compute(count).setName("Atmosphere init");

  const step = Fn(() => {
    const p = pos.element(instanceIndex);
    const seed = hash(instanceIndex.add(101));
    const wind = mx_noise_vec3(p.mul(0.07).add(vec3(0, time.mul(0.05), time.mul(0.03))));
    // fireflies fly their own looping paths; dust is carried by the wind and sinks slowly
    const wander = mx_noise_vec3(p.mul(0.35).add(seed.mul(40)).add(time.mul(0.4))).mul(mix(0.25, 1.4, dark));
    const drift = wind.mul(mix(1.2, 0.5, dark)).add(wander).add(vec3(0.15, mix(-0.12, 0, dark), 0));
    p.addAssign(drift.mul(deltaTime));
    const rel = p.sub(center).add(half);        // wrap into the box around the visitor
    const wrapped = rel.sub(half.mul(2).mul(rel.div(half.mul(2)).floor()));
    p.assign(center.add(wrapped).sub(half));
    p.y.assign(p.y.max(0.15).min(16));
  })().compute(count).setName("Atmosphere step");

  const mat = new T.SpriteNodeMaterial();
  mat.positionNode = pos.toAttribute();
  const id = instanceIndex;
  const pulse = sin(time.mul(mix(0.6, 3.2, dark)).add(hash(id).mul(60))).mul(0.5).add(0.5);
  const shown = hash(id.add(5)).lessThan(mix(1.0, 0.3, dark)).select(1, 0);   // every mote is drawn by day; by night 30% become fireflies
  mat.scaleNode = mix(0.03, 0.07, dark).mul(mix(1, pulse.mul(0.7).add(0.5), dark));
  mat.colorNode = mix(vec3(0.95, 0.9, 0.8).mul(0.5), vec3(1.0, 0.9, 0.4).mul(2.2), dark);
  mat.opacityNode = shapeCircle().mul(shown).mul(mix(0.3, pulse.add(0.1).min(1), dark));
  mat.transparent = true; mat.depthWrite = false;
  mat.blending = T.AdditiveBlending;
  const sprites = new T.Sprite(mat);
  sprites.count = count; sprites.frustumCulled = false; sprites.renderOrder = 5;
  scene.add(sprites);

  renderer.compute(init);
  let on = true;
  return {
    count,
    enable(v){ on = !!v; sprites.visible = on; },
    update(focus, darkness){
      if (!on) return;
      center.value.set(focus.x, 0, focus.z);
      dark.value = darkness;
      renderer.compute(step);
    },
    dispose(){ scene.remove(sprites); mat.dispose(); },
  };
}
