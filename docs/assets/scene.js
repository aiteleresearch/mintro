/* MINTRO website: the 3D scene behind the page.

   A mint crystal (the MINTRO logo) with a glowing core, a basket of coins in orbit around it, and a stream
   of hashes spiralling into it. Every page section ([data-scene]) has a pose; scrolling blends between
   poses, the mouse tilts the camera, and a click spins the crystal. Quality drops by itself on slow GPUs. */

import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

const TAU = Math.PI * 2;
const root = document.documentElement;
const canvas = document.getElementById('gl');
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const coarse = matchMedia('(pointer: coarse)').matches;
let quality = coarse || Math.min(innerWidth, innerHeight) < 600 ? 1 : 2; // 2 high, 1 medium, 0 low

function fail(err) {
  root.classList.add('no-gl');
  dispatchEvent(new Event('mintro:scene-failed'));
  if (err) console.warn('MINTRO: 3D scene off.', err);
}

let renderer = null;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance', stencil: false });
} catch (err) {
  fail(err);
}
if (renderer) start().catch(fail);

/* ---------- poses ---------- */

const BASE = { cx: 0, cy: 0, cs: 1, ringR: 2.2, tilt: 0.3, roll: -0.2, coin: 1, extra: 0, grid: 0, floor: 0,
               camZ: 8, camY: 0, stream: 1, glow: 1, gold: 0, dim: 0 };
// cx/cy: crystal position (mcx/mcy on portrait screens), cs: crystal scale, tilt/roll: orbit plane,
// coin: coin size, extra: engine orbits, grid/floor: CPU-core grid, dim: darken behind text, gold: listing tint
const POSES = {
  hero:     { cx: 2.05, cy: 0.05, mcy: 1.35, cs: 0.92, ringR: 1.75, tilt: 0.32, roll: -0.24 },
  showcase: { cx: 0, cy: 0.1, cs: 0.6, ringR: 3.5, tilt: 0.12, roll: 0.05, coin: 0.85, camZ: 9.5, stream: 0.5, glow: 0.75, dim: 0.35 },
  numbers:  { cx: 0, cy: -2.1, mcy: -3.4, cs: 0.4, ringR: 3.2, tilt: 0.08, roll: 0, coin: 0.6, camZ: 9.5, stream: 0.4, dim: 0.55 },
  clicks:   { cx: 0, cy: 2.05, mcy: 3.3, cs: 0.42, ringR: 1.5, tilt: 0.5, roll: 0, coin: 0.55, camZ: 9, stream: 0.6, dim: 0.3 },
  basket:   { cx: -2.45, mcy: 2.0, cs: 0.78, ringR: 2.05, tilt: 1.05, roll: 0.25, coin: 0.95, stream: 0.85, dim: 0.05 },
  tuned:    { cx: 2.2, cy: 0.55, mcy: 2.2, cs: 0.62, ringR: 1.45, tilt: 0.18, roll: 0, coin: 0.6, grid: 1, floor: 1,
              camY: 2.4, camZ: 8.6, stream: 0.55, dim: 0.05 },
  features: { cx: 0, cy: 0, cs: 0.5, ringR: 3.9, tilt: 0.42, roll: -0.15, coin: 0.8, extra: 1, camZ: 9.5, stream: 0.35, dim: 0.6 },
  honest:   { cx: 3.4, cy: -1.9, mcy: -3.6, cs: 0.4, ringR: 1.2, tilt: 0.3, roll: 0, coin: 0.45, camZ: 10, stream: 0.2,
              glow: 0.6, dim: 0.6 },
  listing:  { cx: -2.25, cy: 0.1, mcy: 2.2, cs: 0.85, ringR: 1.9, tilt: 0.5, roll: 0.3, coin: 0.9, gold: 1, stream: 0.75, dim: 0.1 },
  faq:      { cx: 2.7, cy: -0.4, mcy: 2.6, cs: 0.5, ringR: 1.4, tilt: 0.3, coin: 0.5, stream: 0.3, dim: 0.55 },
  cta:      { cx: 0, cy: 1.75, mcy: 2.6, cs: 0.66, ringR: 2.2, tilt: 0.16, roll: 0.06, coin: 0.75, camZ: 9.5, stream: 1.0, glow: 1.1 },
};
const KEYS = Object.keys(BASE);

/* ---------- shaders ---------- */

const STREAM_VERT = /* glsl */`
  uniform float uTime, uSize, uPR, uIntensity;
  uniform vec3 uA, uB;
  attribute vec4 aSeed;   // start angle, orbit size, speed, phase
  attribute vec2 aExtra;  // height, point size
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    float life = fract(aSeed.w + uTime * aSeed.z);
    float k = pow(life, 1.7);
    float r = mix(2.2 + aSeed.y * 5.5, 0.12, k);
    float a = aSeed.x + k * (3.0 + aSeed.y * 3.0);
    float h = aExtra.x * (0.15 + 2.6 * (1.0 - k));
    vec4 mv = modelViewMatrix * vec4(cos(a) * r, h, sin(a) * r, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * aExtra.y * uPR * (0.35 + 0.65 * k) / -mv.z;
    vAlpha = smoothstep(0.0, 0.2, life) * (1.0 - smoothstep(0.9, 1.0, life)) * uIntensity;
    vColor = mix(uA, uB, k);
  }`;
const STREAM_FRAG = /* glsl */`
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    float a = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
    gl_FragColor = vec4(vColor, a * a * vAlpha);
  }`;
const DUST_VERT = /* glsl */`
  uniform float uTime, uPR;
  attribute float aPhase;
  varying float vA;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = (1.0 + 1.8 * fract(aPhase * 7.31)) * uPR * 24.0 / -mv.z;
    vA = 0.25 + 0.75 * (0.5 + 0.5 * sin(uTime * 0.9 + aPhase * 6.2831));
  }`;
const DUST_FRAG = /* glsl */`
  varying float vA;
  void main() {
    float a = smoothstep(0.5, 0.0, length(gl_PointCoord - 0.5));
    gl_FragColor = vec4(vec3(0.72, 0.95, 0.85), a * vA * 0.4);
  }`;
const FLOOR_VERT = /* glsl */`
  varying vec3 vWorld;
  void main() {
    vec4 w = modelMatrix * vec4(position, 1.0);
    vWorld = w.xyz;
    gl_Position = projectionMatrix * viewMatrix * w;
  }`;
const FLOOR_FRAG = /* glsl */`
  uniform float uOpacity;
  uniform vec3 uColor, uCenter;
  varying vec3 vWorld;
  void main() {
    vec2 p = vWorld.xz / 0.38;
    vec2 g = abs(fract(p - 0.5) - 0.5) / fwidth(p);
    float line = 1.0 - min(min(g.x, g.y), 1.0);
    float fade = 1.0 - smoothstep(0.8, 7.5, length(vWorld.xz - uCenter.xz));
    gl_FragColor = vec4(uColor, line * fade * uOpacity * 0.45);
  }`;

/* ---------- scene ---------- */

async function start() {
  // Coin faces use the page's display font; give it a moment to load
  await Promise.race([document.fonts.load('700 64px Sora'), new Promise((r) => setTimeout(r, 600))]).catch(() => {});

  const dpr = () => Math.min(devicePixelRatio || 1, [1, 1.25, 1.5][quality]);
  renderer.setPixelRatio(dpr());
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.9;

  const BG = new THREE.Color('#050607');
  const scene = new THREE.Scene();
  scene.background = BG;
  scene.fog = new THREE.Fog(BG, 12, 36);
  const camera = new THREE.PerspectiveCamera(35, innerWidth / innerHeight, 0.1, 120);

  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;
  scene.environmentIntensity = 0.7; // the studio-light reflections are bright on a dark page
  pmrem.dispose();

  const C = {
    mint: new THREE.Color('#3ddc97'), mintLight: new THREE.Color('#a6f7d2'), mintDeep: new THREE.Color('#0f9d6b'),
    mintSolid: new THREE.Color('#1d9e6c'),
    gold: new THREE.Color('#f2c46d'), goldLight: new THREE.Color('#ffe7b0'), goldDeep: new THREE.Color('#b8862e'),
    goldSolid: new THREE.Color('#c99a3e'),
  };
  const mix = (a, b, t, out) => out.copy(a).lerp(b, t);

  const key = new THREE.DirectionalLight(0xffffff, 0.9);
  key.position.set(4, 6, 5);
  const rim = new THREE.DirectionalLight(C.mint.clone(), 0.8);
  rim.position.set(-6, 2, -4);
  scene.add(key, rim);

  // The crystal: a brilliant-cut take on the MINTRO diamond, glass with dispersion, a glowing core inside
  const crystal = new THREE.Group();
  scene.add(crystal);
  const gemGeo = new THREE.LatheGeometry(
    [[0, 1.32], [0.42, 0.8], [0.82, 0.2], [0.9, 0.05], [0.9, -0.05], [0.52, -0.6], [0, -1.32]].map(([x, y]) => new THREE.Vector2(x, y)),
    8, Math.PI / 8);
  // Tinted glass without real transmission: each facet catches the environment differently, the core glows
  // softly through it, and it costs one draw instead of a second scene render
  const gemMat = new THREE.MeshPhysicalMaterial({
    color: C.mintSolid.clone(), metalness: 0.35, roughness: 0.2, iridescence: 0.55, iridescenceIOR: 1.3,
    envMapIntensity: 1.1, emissive: 0x03190f, flatShading: true, transparent: true, opacity: 0.86, depthWrite: false,
  });
  const gem = new THREE.Mesh(gemGeo, gemMat);
  const edgeMat = new THREE.LineBasicMaterial({ color: C.mintLight.clone(), transparent: true, opacity: 0.38 });
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(gemGeo, 10), edgeMat);
  edges.scale.setScalar(1.003);
  const coreMat = new THREE.MeshBasicMaterial({ color: C.mint.clone() });
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.3, 1), coreMat);
  const shellGeo = new THREE.OctahedronGeometry(0.62, 0);
  shellGeo.scale(1, 1.3, 1);
  const shellMat = new THREE.LineBasicMaterial({ color: C.mintLight.clone().multiplyScalar(1.4) });
  const shell = new THREE.LineSegments(new THREE.EdgesGeometry(shellGeo), shellMat);
  crystal.add(core, shell, gem, edges);

  const lattice = new THREE.Group();
  const latGeo = new THREE.OctahedronGeometry(1.55, 0);
  latGeo.scale(1, 1.3, 1);
  const latMat = new THREE.LineBasicMaterial({ color: C.mint.clone(), transparent: true, opacity: 0.16 });
  lattice.add(new THREE.LineSegments(new THREE.EdgesGeometry(latGeo), latMat));
  const nodeGeo = new THREE.SphereGeometry(0.028, 12, 8);
  const nodeMat = new THREE.MeshBasicMaterial({ color: C.mintLight.clone() });
  const seen = new Set();
  const lp = latGeo.attributes.position;
  for (let i = 0; i < lp.count; i++) {
    const k = [lp.getX(i), lp.getY(i), lp.getZ(i)].map((v) => v.toFixed(2)).join();
    if (seen.has(k)) continue;
    seen.add(k);
    const n = new THREE.Mesh(nodeGeo, nodeMat);
    n.position.fromBufferAttribute(lp, i);
    lattice.add(n);
  }
  crystal.add(lattice);

  // The basket: coins in orbit
  const METALS = { gold: ['#d8b25c', '#f6dc9a', '#7a5718'], mint: ['#2fbf86', '#a5f5d0', '#0b5e40'],
                   silver: ['#9aa3aa', '#d5dbe0', '#4c555c'] };
  const COINS = [['XMR', 'gold'], ['ZEPH', 'mint'], ['SAL', 'silver'], ['RTM', 'gold'], ['YTN', 'mint'], ['FIRO', 'silver'],
                 ['MEWC', 'gold'], ['MYT', 'mint'], ['BMR', 'silver'], ['CAS', 'gold'], ['NEW', 'mint'], ['???', 'silver']];
  const coinGeo = new THREE.CylinderGeometry(0.3, 0.3, 0.055, 56, 1);
  coinGeo.rotateX(Math.PI / 2); // faces look at the camera
  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  function coinFace(label, base, light, dark) {
    const s = 256, cv = document.createElement('canvas');
    cv.width = cv.height = s;
    const g = cv.getContext('2d');
    const bg = g.createRadialGradient(s * 0.36, s * 0.3, s * 0.04, s / 2, s / 2, s * 0.64);
    bg.addColorStop(0, light); bg.addColorStop(0.55, base); bg.addColorStop(1, dark);
    g.fillStyle = bg;
    g.fillRect(0, 0, s, s);
    g.lineWidth = 7; g.strokeStyle = 'rgba(255,255,255,.45)';
    g.beginPath(); g.arc(s / 2, s / 2, s * 0.43, 0, TAU); g.stroke();
    g.lineWidth = 2; g.strokeStyle = 'rgba(0,0,0,.3)';
    g.beginPath(); g.arc(s / 2, s / 2, s * 0.385, 0, TAU); g.stroke();
    g.save(); g.translate(s / 2, s / 2);
    for (let i = 0; i < 72; i++) {
      g.rotate(TAU / 72);
      g.fillStyle = i % 2 ? 'rgba(0,0,0,.2)' : 'rgba(255,255,255,.24)';
      g.fillRect(-1.5, -s * 0.49, 3, s * 0.045);
    }
    g.restore();
    g.font = `700 ${label.length > 3 ? 52 : 64}px Sora, "Segoe UI", sans-serif`;
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillStyle = 'rgba(0,0,0,.35)'; g.fillText(label, s / 2 + 2, s / 2 + 5);
    g.fillStyle = 'rgba(255,255,255,.96)'; g.fillText(label, s / 2, s / 2 + 2);
    const t = new THREE.CanvasTexture(cv);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = maxAniso;
    t.center.set(0.5, 0.5);
    t.rotation = Math.PI / 2; // cylinder caps map the texture sideways
    return t;
  }
  const coins = COINS.slice(0, quality === 2 ? 12 : 9).map(([label, metal], i) => {
    const [base, light, dark] = METALS[metal];
    const face = new THREE.MeshStandardMaterial({ map: coinFace(label, base, light, dark), metalness: 0.8, roughness: 0.4, envMapIntensity: 0.6 });
    const side = new THREE.MeshStandardMaterial({ color: base, metalness: 1, roughness: 0.34, envMapIntensity: 0.6 });
    const m = new THREE.Mesh(coinGeo, [side, face, face]);
    m.userData = { phase: i * 1.7, bob: Math.random() * TAU };
    scene.add(m);
    return m;
  });
  const ring = new THREE.Group();
  const orbitMat = new THREE.MeshBasicMaterial({ color: C.mint.clone().multiplyScalar(1.2), transparent: true, opacity: 0 });
  const orbit = new THREE.Mesh(new THREE.TorusGeometry(1, 0.0035, 6, 220), orbitMat);
  orbit.rotation.x = Math.PI / 2;
  ring.add(orbit);
  scene.add(ring);

  // Engine orbits (the "Inside" section)
  const extra = new THREE.Group();
  const extraMat = new THREE.MeshBasicMaterial({ color: C.mintLight.clone(), transparent: true, opacity: 0 });
  const beadMat = new THREE.MeshBasicMaterial({ color: C.mintLight.clone().multiplyScalar(3), transparent: true, opacity: 0 });
  const beadGeo = new THREE.SphereGeometry(0.05, 12, 8);
  const orbits = [[1.0, 0.3, 0.7, 2.9], [-0.8, -0.2, -0.9, 3.4], [0.15, 0.9, 0.2, 3.9]].map(([x, y, z, r]) => {
    const g = new THREE.Group();
    g.rotation.set(x, y, z);
    g.add(new THREE.Mesh(new THREE.TorusGeometry(r, 0.004, 6, 200), extraMat));
    const beads = [0, 1, 2].map(() => { const b = new THREE.Mesh(beadGeo, beadMat); g.add(b); return b; });
    extra.add(g);
    return { g, r, beads };
  });
  scene.add(extra);

  // The hash stream
  const streamCount = [1200, 2400, 4200][quality];
  const sGeo = new THREE.BufferGeometry();
  const seed = new Float32Array(streamCount * 4), sx = new Float32Array(streamCount * 2);
  for (let i = 0; i < streamCount; i++) {
    seed.set([Math.random() * TAU, Math.random(), 0.05 + Math.random() * 0.12, Math.random()], i * 4);
    sx.set([Math.random() * 2 - 1, 0.4 + Math.random() * 1.2], i * 2);
  }
  sGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(streamCount * 3), 3));
  sGeo.setAttribute('aSeed', new THREE.BufferAttribute(seed, 4));
  sGeo.setAttribute('aExtra', new THREE.BufferAttribute(sx, 2));
  const streamMat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uSize: { value: 22 }, uPR: { value: 1 }, uIntensity: { value: 0 },
                uA: { value: C.mintLight.clone() }, uB: { value: C.mint.clone() } },
    vertexShader: STREAM_VERT, fragmentShader: STREAM_FRAG,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const stream = new THREE.Points(sGeo, streamMat);
  stream.frustumCulled = false;
  scene.add(stream);

  // Distant dust
  const dustCount = quality === 2 ? 900 : 500;
  const dGeo = new THREE.BufferGeometry();
  const dPos = new Float32Array(dustCount * 3), dPhase = new Float32Array(dustCount);
  for (let i = 0; i < dustCount; i++) {
    const r = 10 + Math.random() * 28, th = Math.random() * TAU, ph = Math.acos(Math.random() * 2 - 1);
    dPos.set([r * Math.sin(ph) * Math.cos(th), r * Math.cos(ph) * 0.6, r * Math.sin(ph) * Math.sin(th) - 6], i * 3);
    dPhase[i] = Math.random();
  }
  dGeo.setAttribute('position', new THREE.BufferAttribute(dPos, 3));
  dGeo.setAttribute('aPhase', new THREE.BufferAttribute(dPhase, 1));
  const dustMat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uPR: { value: 1 } }, vertexShader: DUST_VERT, fragmentShader: DUST_FRAG,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const dust = new THREE.Points(dGeo, dustMat);
  scene.add(dust);

  // CPU cores (the "Auto mode" section): one tile per thread, lit when MINTRO uses it
  const COLS = 6, ROWS = 4, CELLS = COLS * ROWS;
  const cellMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0 });
  const grid = new THREE.InstancedMesh(new RoundedBoxGeometry(0.3, 0.07, 0.3, 2, 0.025), cellMat, CELLS);
  const m4 = new THREE.Matrix4(), cellColor = new THREE.Color(), cellOff = new THREE.Color('#0d1512');
  const cellLevel = new Float32Array(CELLS);
  for (let i = 0; i < CELLS; i++) {
    m4.makeTranslation(((i % COLS) - (COLS - 1) / 2) * 0.38, 0, (Math.floor(i / COLS) - (ROWS - 1) / 2) * 0.38);
    grid.setMatrixAt(i, m4);
    grid.setColorAt(i, cellOff);
  }
  scene.add(grid);
  const floorMat = new THREE.ShaderMaterial({
    uniforms: { uOpacity: { value: 0 }, uColor: { value: C.mint.clone() }, uCenter: { value: new THREE.Vector3() } },
    vertexShader: FLOOR_VERT, fragmentShader: FLOOR_FRAG, transparent: true, depthWrite: false,
  });
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), floorMat);
  floor.rotation.x = -Math.PI / 2;
  scene.add(floor);

  // Post-processing: a gentle bloom on the brightest bits only, then tone mapping
  const rt = new THREE.WebGLRenderTarget(2, 2, { type: THREE.HalfFloatType, samples: quality === 2 ? 2 : 0 });
  const composer = new EffectComposer(renderer, rt);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(2, 2), 0.35, 0.4, 1.25);
  bloom.enabled = quality === 2; // phones and weaker GPUs skip it
  const bloomSize = bloom.setSize.bind(bloom);
  bloom.setSize = (w, h) => bloomSize(w / 2, h / 2); // a soft glow doesn't need full resolution
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  /* ---------- layout ---------- */

  let portrait = false, poses = {}, anchors = [], width = 0, height = 0;
  function pose(name) {
    const p = { ...BASE, ...POSES[name] };
    if (portrait) {
      p.cx = p.mcx ?? 0;
      p.cy = p.mcy ?? p.cy;
      p.camZ *= 1.62;
      p.ringR *= 0.9;
      if (name !== 'hero' && name !== 'cta') p.dim = Math.min(1, p.dim + 0.25);
    }
    return p;
  }
  function measure() {
    anchors = [...document.querySelectorAll('[data-scene]')].map((el) => {
      const r = el.getBoundingClientRect();
      return { at: r.top + scrollY + r.height / 2 - innerHeight / 2, name: el.dataset.scene };
    }).filter((a) => POSES[a.name]).sort((a, b) => a.at - b.at);
    if (anchors.length) anchors[0].at = Math.min(anchors[0].at, 0);
  }
  function resize(force) {
    const w = innerWidth, h = innerHeight;
    if (!force) {
      if (w === width && h === height) return;
      // Phones resize the viewport as the address bar slides; ignore small height changes there
      if (coarse && w === width && Math.abs(h - height) < 150) return;
    }
    width = w; height = h;
    portrait = w / h < 0.85;
    renderer.setPixelRatio(dpr());
    renderer.setSize(w, h, false);
    composer.setPixelRatio(dpr());
    composer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    poses = Object.fromEntries(Object.keys(POSES).map((n) => [n, pose(n)]));
    measure();
  }
  resize(true);
  new ResizeObserver(() => measure()).observe(document.body);
  addEventListener('resize', () => resize(false));

  const target = {};
  function computeTarget() {
    if (!anchors.length) { Object.assign(target, poses.hero); return; }
    const y = scrollY;
    let i = 0;
    while (i < anchors.length - 1 && y >= anchors[i + 1].at) i++;
    const a = anchors[i], b = anchors[Math.min(i + 1, anchors.length - 1)];
    let t = b.at > a.at ? (y - a.at) / (b.at - a.at) : 0;
    t = Math.min(1, Math.max(0, (t - 0.12) / 0.76)); // hold each pose for a moment
    t = t * t * (3 - 2 * t);
    const pa = poses[a.name], pb = poses[b.name];
    for (const k of KEYS) target[k] = pa[k] + (pb[k] - pa[k]) * t;
  }

  /* ---------- input ---------- */

  const mouse = { x: 0, y: 0, sx: 0, sy: 0 }, ndc = new THREE.Vector2(9, 9);
  addEventListener('pointermove', (e) => {
    mouse.x = (e.clientX / innerWidth) * 2 - 1;
    mouse.y = -((e.clientY / innerHeight) * 2 - 1);
    ndc.set(mouse.x, mouse.y);
  }, { passive: true });
  let spinVel = 0;
  addEventListener('pointerdown', (e) => {
    if (e.target.closest('a, button, input, summary, details, .tile, .plan, .device, .term')) return;
    spinVel = Math.min(14, spinVel + 6);
  });
  const raycaster = new THREE.Raycaster();

  /* ---------- loop ---------- */

  const cur = { ...poses.hero };
  const motion = reduced ? 0.25 : 1;
  const v = new THREE.Vector3();
  const damp = (a, b, l, dt) => a + (b - a) * (1 - Math.exp(-l * dt));
  const easeOutBack = (x) => 1 + 2.2 * Math.pow(x - 1, 3) + 1.2 * Math.pow(x - 1, 2);
  let last = performance.now(), time = 0, streamTime = 0, ringAngle = 0, spinAngle = 0, intro = 0, hover = 0;
  let lastScroll = scrollY, scrollVel = 0, lastGold = -1, ready = false;
  let perfFrames = 0, perfTime = 0;

  const colors = { glass: new THREE.Color(), att: new THREE.Color(), solid: new THREE.Color(), light: new THREE.Color(),
                   base: new THREE.Color(), deep: new THREE.Color() };
  function tint(gold) {
    mix(C.mintSolid, C.goldSolid, gold, gemMat.color);
    mix(C.mintLight, C.goldLight, gold, colors.light);
    mix(C.mint, C.gold, gold, colors.base);
    edgeMat.color.copy(colors.light).multiplyScalar(1.6);
    latMat.color.copy(colors.base);
    nodeMat.color.copy(colors.light);
    shellMat.color.copy(colors.light).multiplyScalar(1.4);
    orbitMat.color.copy(colors.base).multiplyScalar(1.2);
    extraMat.color.copy(colors.light);
    beadMat.color.copy(colors.light).multiplyScalar(3);
    streamMat.uniforms.uA.value.copy(colors.light);
    streamMat.uniforms.uB.value.copy(colors.base);
    rim.color.copy(colors.base);
  }

  function downgrade() {
    if (quality === 0) return;
    quality--;
    bloom.enabled = false;
    if (quality === 0) {
      sGeo.setDrawRange(0, Math.floor(streamCount / 2));
    }
    resize(true);
    root.dataset.quality = quality;
  }

  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (dt <= 0 || document.hidden) return;
    update(dt);
    // After the intro, watch the frame rate for two seconds and step down if this GPU struggles
    if (intro >= 1 && quality > 0) {
      perfFrames++;
      perfTime += dt;
      if (perfFrames >= 120) {
        if (perfTime / perfFrames > 1 / 40) downgrade();
        perfFrames = perfTime = 0;
      }
    }
  }

  function update(dt) {
    time += dt * motion;
    intro = Math.min(1, intro + dt / 2.4);
    const ei = 1 - Math.pow(1 - intro, 4);
    const pop = easeOutBack(Math.min(1, intro * 1.3));

    computeTarget();
    for (const k of KEYS) cur[k] = damp(cur[k], target[k], 2.6, dt);
    const sy = scrollY;
    scrollVel = damp(scrollVel, (sy - lastScroll) / dt, 5, dt);
    lastScroll = sy;
    mouse.sx = damp(mouse.sx, mouse.x, 3, dt);
    mouse.sy = damp(mouse.sy, mouse.y, 3, dt);

    camera.position.set(mouse.sx * 0.45, cur.camY + mouse.sy * 0.3, cur.camZ);
    camera.lookAt(0, cur.camY * 0.28, 0);
    scene.fog.near = cur.camZ + 3;
    scene.fog.far = cur.camZ + 30;

    // Crystal
    crystal.position.set(cur.cx, cur.cy + Math.sin(time * 0.8) * 0.06, 0);
    crystal.scale.setScalar(Math.max(0.001, cur.cs * pop));
    spinVel *= Math.exp(-1.4 * dt);
    spinAngle += dt * (0.35 * motion + spinVel) + scrollVel * dt * 0.0006;
    gem.rotation.set(Math.sin(time * 0.3) * 0.08 + mouse.sy * 0.25, spinAngle + mouse.sx * 0.5, 0);
    edges.rotation.copy(gem.rotation);
    core.rotation.set(time * 0.7, time * 1.1, 0);
    shell.rotation.set(time * 0.25, -time * 0.4, 0);
    lattice.rotation.set(0, -spinAngle * 0.45, Math.sin(time * 0.2) * 0.1);

    raycaster.setFromCamera(ndc, camera);
    hover = damp(hover, raycaster.intersectObject(gem, false).length ? 1 : 0, 6, dt);
    const pulse = 0.5 + 0.5 * Math.sin(time * 2.2);
    if (Math.abs(cur.gold - lastGold) > 0.002) { tint(cur.gold); lastGold = cur.gold; }
    coreMat.color.copy(colors.base).multiplyScalar((1.15 + pulse * 0.3 + hover * 0.6 + spinVel * 0.05) * cur.glow);
    core.scale.setScalar(1 + hover * 0.25 + pulse * 0.06);

    // Basket orbit
    ring.position.copy(crystal.position);
    ring.rotation.set(cur.tilt, 0, cur.roll);
    const R = cur.ringR * (1 + (1 - ei) * 2.5);
    orbit.scale.set(R, R, 1);
    orbitMat.opacity = 0.3 * ei;
    ringAngle += dt * motion * 0.16 + scrollVel * dt * 0.00035;
    for (let i = 0; i < coins.length; i++) {
      const m = coins[i], a = ringAngle + (i / coins.length) * TAU;
      v.set(Math.cos(a) * R, Math.sin(time * 1.1 + m.userData.bob) * 0.05, Math.sin(a) * R)
        .applyEuler(ring.rotation).add(crystal.position);
      m.position.copy(v);
      m.scale.setScalar(Math.max(0.001, cur.coin * ei));
      m.rotation.set(Math.sin(time * 0.6 + i) * 0.25, Math.sin(time * 0.7 + m.userData.phase) * 0.9, Math.sin(time * 0.5 + i) * 0.1);
    }

    // Engine orbits
    extra.visible = cur.extra > 0.01;
    if (extra.visible) {
      extra.position.copy(crystal.position);
      extraMat.opacity = 0.22 * cur.extra * ei;
      beadMat.opacity = cur.extra * ei;
      orbits.forEach((o, j) => {
        o.g.rotation.z += dt * 0.08 * motion * (j % 2 ? -1 : 1);
        o.beads.forEach((b, k) => {
          const a = time * (0.45 + j * 0.12) + (k / 3) * TAU;
          b.position.set(Math.cos(a) * o.r, Math.sin(a) * o.r, 0);
        });
      });
    }

    // Hash stream and dust
    stream.position.copy(crystal.position);
    stream.scale.setScalar(Math.max(0.001, cur.cs));
    stream.rotation.y += dt * 0.05 * motion;
    streamTime += dt * motion * (0.6 + cur.stream);
    streamMat.uniforms.uTime.value = streamTime;
    streamMat.uniforms.uIntensity.value = Math.min(1.2, cur.stream) * 0.55 * ei;
    streamMat.uniforms.uPR.value = renderer.getPixelRatio();
    dust.rotation.y = time * 0.012;
    dustMat.uniforms.uTime.value = time;
    dustMat.uniforms.uPR.value = renderer.getPixelRatio();

    // CPU cores
    grid.visible = floor.visible = cur.grid > 0.01;
    if (grid.visible) {
      cellMat.opacity = cur.grid;
      grid.position.set(crystal.position.x, crystal.position.y - 1.55, 0);
      grid.scale.setScalar(0.85 + 0.15 * cur.grid);
      const active = 10 + Math.round(4 * Math.sin(time * 0.6));
      const step = Math.floor(time * 1.6);
      for (let i = 0; i < CELLS; i++) {
        const on = ((i * 7 + step) % CELLS) < active ? 1 : 0;
        cellLevel[i] = damp(cellLevel[i], on, 5, dt);
        cellColor.copy(cellOff).lerp(colors.base, cellLevel[i]).multiplyScalar(1 + cellLevel[i] * 1.6);
        grid.setColorAt(i, cellColor);
      }
      grid.instanceColor.needsUpdate = true;
      floorMat.uniforms.uOpacity.value = cur.floor;
      floor.position.set(crystal.position.x, grid.position.y - 0.06, 0);
      floorMat.uniforms.uCenter.value.copy(floor.position);
      floorMat.uniforms.uColor.value.copy(colors.base);
    }

    renderer.toneMappingExposure = 0.9 * (1 - cur.dim * 0.5);
    bloom.strength = 0.35 * cur.glow * (1 - cur.dim * 0.5) * ei;
    composer.render(dt);

    if (!ready) {
      ready = true;
      root.classList.add('gl-ready');
      dispatchEvent(new Event('mintro:scene-ready'));
    }
  }

  addEventListener('visibilitychange', () => { last = performance.now(); });
  canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); fail(); });
  root.dataset.quality = quality;
  requestAnimationFrame(frame);
}
