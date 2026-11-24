/* MIST console — shell, state, router, live polling, formatting.
 *
 * Vanilla ES modules. No build step, no CDN, no external fonts.
 * Served at /api/static/app.js (modules resolve relatively, e.g. ./views/world.js).
 *
 * Contract: API.md. Every panel renders an honest "—" or an inline error; a
 * failing source never blanks the view and never throws out of a render.
 */

export const POLL_MS = 5000;              /* /api/world + /api/colony cadence  */
export const STALE_AFTER_MS = POLL_MS * 3;/* last-good older than this = stale */
export const TALK_TIMEOUT_MS = 180000;    /* one live model call               */
export const ASSEMBLY_TIMEOUT_MS = 900000;/* N calls x rounds, can be long     */
export const READ_TIMEOUT_MS = 30000;

/* ====================================================================== fmt */

const ENT = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"};
export function esc(v){ return String(v == null ? "" : v).replace(/[&<>"']/g, c => ENT[c]); }
export function s(v){ return v == null ? "" : String(v); }
/* escaped-or-dash for leaf values */
export function dsh(v){ return (v == null || v === "") ? "—" : esc(v); }
/* raw-or-dash for values that are already HTML fragments */
export function rh(v){ return (v == null || v === "") ? "—" : v; }
export function has(v){ return v != null && v !== ""; }

export function num(v){
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!isFinite(n)) return esc(v);
  return n.toLocaleString("en-US");
}
export function f2(v, d){
  if (d === undefined) d = 2;
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!isFinite(n)) return esc(v);
  return n.toFixed(d);
}
export function msOf(v){
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return n < 1000 ? Math.round(n) + "ms" : (n / 1000).toFixed(2) + "s";
}
export function secsOf(v){
  if (v == null || v === "") return "—";
  let n = Math.round(Number(v));
  if (!isFinite(n)) return "—";
  if (n < 0) n = 0;
  if (n < 60) return n + "s";
  const m = Math.floor(n / 60), h = Math.floor(m / 60), d = Math.floor(h / 24);
  if (h < 1) return m + "m " + (n % 60) + "s";
  if (d < 1) return h + "h " + (m % 60) + "m";
  return d + "d " + (h % 24) + "h";
}
/* tolerant wall-clock: seconds, milliseconds or ISO string */
export function clockOf(v){
  if (v == null || v === "") return "—";
  if (typeof v === "string" && !/^-?\d+(\.\d+)?$/.test(v)){
    const d = new Date(v);
    return isNaN(d.getTime()) ? esc(v) : d.toLocaleString([], {hour12: false});
  }
  let n = Number(v);
  if (!isFinite(n) || n <= 0) return "—";
  if (n > 1e12) n = n / 1000;
  const d = new Date(n * 1000);
  return isNaN(d.getTime()) ? esc(v) : d.toLocaleString([], {hour12: false});
}
export function timeOf(v){
  if (v == null || v === "") return "—";
  if (typeof v === "string" && !/^-?\d+(\.\d+)?$/.test(v)){
    const d = new Date(v);
    return isNaN(d.getTime()) ? esc(v) : d.toLocaleTimeString([], {hour12: false});
  }
  let n = Number(v);
  if (!isFinite(n) || n <= 0) return "—";
  if (n > 1e12) n = n / 1000;
  return new Date(n * 1000).toLocaleTimeString([], {hour12: false});
}
/* "how long ago", tolerant of the same three shapes */
export function agoOf(v){
  if (v == null || v === "") return "—";
  let n;
  if (typeof v === "string" && !/^-?\d+(\.\d+)?$/.test(v)) n = new Date(v).getTime() / 1000;
  else { n = Number(v); if (n > 1e12) n = n / 1000; }
  if (!isFinite(n) || n <= 0) return "—";
  return secsOf(Date.now() / 1000 - n) + " ago";
}
export function pctOf(part, whole){
  const p = Number(part), w = Number(whole);
  if (!isFinite(p) || !isFinite(w) || w <= 0) return null;
  return 100 * p / w;
}

/* ================================================================== widgets */

export function chip(html, cls){
  return `<span class="chip ${cls || ""}">${html}</span>`;
}
export function bis(v){ return v ? chip("yes", "on") : chip("no", "off"); }
export function updown(up, onText, offText){
  return up ? chip(onText || "up", "on") : chip(offText || "down", "off");
}
export function bar(frac, opts){
  const o = opts || {};
  let p = (frac == null || !isFinite(Number(frac))) ? 0 : Number(frac);
  p = Math.max(0, Math.min(1, p));
  let cls = "bar";
  if (o.warn != null && p >= o.warn) cls += " warn";
  if (o.bad != null && p >= o.bad) cls += " bad";
  if (o.thin) cls += " thin";
  return `<div class="${cls}"><i style="width:${(p * 100).toFixed(1)}%"></i></div>`;
}
export function barrow(label, used, limit, opts){
  const o = opts || {};
  const p = (limit != null && Number(limit) > 0) ? Number(used) / Number(limit) : (o.frac || 0);
  const right = (o.right != null) ? o.right
    : `${num(used)}${limit != null ? " / " + num(limit) : ""}`;
  return `<div class="barlabel"><span>${esc(label)}</span><span class="mono">${right}</span></div>`
       + bar(p, o);
}
export function kv(k, v, cls){
  return `<div class="kv ${cls || ""}"><span class="k">${esc(k)}</span>`
       + `<span class="v">${v == null ? "—" : v}</span></div>`;
}
export function kvw(k, v){
  return `<div class="kv wide"><span class="k">${esc(k)}</span>`
       + `<span class="v">${v == null ? "—" : v}</span></div>`;
}
export function panel(title, body, opts){
  const o = opts || {};
  return `<section class="panel ${o.cls || ""}"${o.id ? ` id="${esc(o.id)}"` : ""}>`
       + `<div class="phead"><h2>${esc(title)}</h2>`
       + `<span class="pmeta">${o.meta || ""}</span></div>`
       + `<div class="pbody">${body}</div></section>`;
}
export function table(cols, rows, opts){
  const o = opts || {};
  if (!rows || !rows.length) return `<div class="empty">${esc(o.empty || "nothing here")}</div>`;
  const head = cols.map(c => {
    if (typeof c === "string") return `<th>${esc(c)}</th>`;
    return `<th class="${c.cls || ""}">${esc(c.label)}</th>`;
  }).join("");
  const body = rows.map(r => `<tr>${r.map(c => `<td>${c == null ? "—" : c}</td>`).join("")}</tr>`).join("");
  return `<div class="scrolly ${o.scroll || ""}" data-scroll="${esc(o.key || "tbl")}">`
       + `<table class="tbl ${o.cls || ""}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
export function pre(text, cls){
  return `<div class="scrolly short" data-scroll="pre-${esc(cls || "x")}"><pre>${esc(text == null || text === "" ? "—" : text)}</pre></div>`;
}
export function empty(msg){ return `<div class="empty">${esc(msg)}</div>`; }
export function note(msg){ return `<div class="note">${esc(msg)}</div>`; }
export function errbox(msg){ return `<div class="errbox">${esc(msg)}</div>`; }
export function raw(v){
  let t;
  try { t = JSON.stringify(v, null, 1); } catch (e) { t = String(v); }
  if (t == null) t = String(v);
  return `<div class="scrolly short" data-scroll="raw"><pre class="raw">${esc(t)}</pre></div>`;
}
export function hyper(href, label, cls){
  return `<a href="${esc(href)}"${cls ? ` class="${esc(cls)}"` : ""}>${esc(label)}</a>`;
}
export function staleTag(at, now){
  if (!at) return "";
  const age = (now || Date.now()) - at;
  if (age < STALE_AFTER_MS) return "";
  return chip("stale " + secsOf(age / 1000), "warnb");
}
export function sourceTag(at, err, now){
  if (err) return chip("error", "off") + " " + chip("last good " + (at ? agoOf(at / 1000) : "—"), "warnb");
  return staleTag(at, now);
}

/* ================================================================== fetching */

async function jfetch(path, opts){
  const o = opts || {};
  const timeout = o.timeout || READ_TIMEOUT_MS;
  const ctl = (typeof AbortController !== "undefined") ? new AbortController() : null;
  const to = ctl ? setTimeout(() => ctl.abort(), timeout) : null;
  const t0 = Date.now();
  try {
    const init = {method: o.method || "GET", cache: "no-store", headers: {}};
    if (ctl) init.signal = ctl.signal;
    if (o.body != null){
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(o.body);
    }
    const resp = await fetch(path, init);
    const text = await resp.text();
    let data = null, bad = false;
    if (text){ try { data = JSON.parse(text); } catch (e) { bad = true; } }
    const at = Date.now();
    if (!resp.ok){
      const msg = (data && data.error) ? String(data.error) : ("HTTP " + resp.status);
      return {ok: false, status: resp.status, error: msg, data: data, at: at, ms: at - t0};
    }
    if (bad) return {ok: false, status: resp.status, error: "malformed JSON from server", at: at, ms: at - t0};
    return {ok: true, status: resp.status, data: data, at: at, ms: at - t0};
  } catch (e){
    const at = Date.now();
    const msg = (e && e.name === "AbortError")
      ? ("no answer within " + Math.round(timeout / 1000) + "s")
      : ((e && e.message) ? e.message : String(e));
    return {ok: false, error: msg, offline: true, at: at, ms: at - t0};
  } finally {
    if (to) clearTimeout(to);
  }
}
export function getJSON(path, opts){ return jfetch(path, opts); }
export function postJSON(path, body, opts){
  return jfetch(path, Object.assign({}, opts || {}, {method: "POST", body: body}));
}

/* ===================================================================== state */

export const state = {
  world: null, worldAt: 0, worldErr: null, worldErrAt: 0,
  colony: null, colonyAt: 0, colonyErr: null, colonyErrAt: 0,
  ci: {},                    /* lname -> {name, data, at, err, status, errAt} */
  assemblies: null, assembliesAt: 0, assembliesErr: null,
  assembly: {},              /* id -> {data, at, err} */
  busy: 0,                   /* in-flight spends (POSTs); poll pauses while > 0 */
  spendNote: "",
  polls: 0,
  lastPollAt: 0,
};

export function beginSpend(note){ state.busy++; if (note) state.spendNote = note; refreshChrome(); }
export function endSpend(){ state.busy = Math.max(0, state.busy - 1); if (!state.busy) state.spendNote = ""; refreshChrome(); }
export function isBusy(){ return state.busy > 0; }

export async function loadWorld(){
  const r = await getJSON("/api/world", {timeout: 30000});
  state.polls++;
  state.lastPollAt = Date.now();
  if (r.ok){ state.world = r.data; state.worldAt = r.at; state.worldErr = null; }
  else { state.worldErr = r.error; state.worldErrAt = r.at; }
  return r;
}
export async function loadColony(){
  const r = await getJSON("/api/colony", {timeout: 30000});
  if (r.ok){ state.colony = r.data; state.colonyAt = r.at; state.colonyErr = null; }
  else { state.colonyErr = r.error; state.colonyErrAt = r.at; }
  return r;
}
export async function loadCI(name){
  const key = String(name || "").toLowerCase();
  if (!key) return {ok: false, error: "no CI named"};
  const r = await getJSON("/api/ci/" + encodeURIComponent(name), {timeout: 30000});
  const slot = state.ci[key] || {name: name};
  const bad = r.data && r.data.error && !r.data.agent;
  if (r.ok && !bad){ slot.data = r.data; slot.at = r.at; slot.err = null; slot.status = r.status; }
  else {
    slot.err = (r.data && r.data.error) || r.error || "unreadable";
    slot.errAt = r.at; slot.status = r.status;
    if (r.status === 404) slot.data = null;
  }
  slot.name = (slot.data && slot.data.agent && slot.data.agent.name) ? slot.data.agent.name : name;
  state.ci[key] = slot;
  return r.ok && !bad ? {ok: true, data: r.data, at: r.at} : {ok: false, error: slot.err, data: r.data, at: r.at, status: r.status};
}
/* Accept either a bare array or a wrapped {assemblies|items|rows: [...]} body:
   API.md specifies a bare array; the live backend currently wraps it. */
function asList(d){
  if (Array.isArray(d)) return d;
  if (d && typeof d === "object"){
    for (const k of ["assemblies", "items", "rows"]) if (Array.isArray(d[k])) return d[k];
  }
  return null;
}
function asObj(d, key){
  if (d && typeof d === "object" && d[key] && typeof d[key] === "object") return d[key];
  return d;
}

export async function loadAssemblies(){
  const r = await getJSON("/api/assemblies", {timeout: 30000});
  const list = asList(r.data);
  if (r.ok && list){ state.assemblies = list; state.assembliesAt = r.at; state.assembliesErr = null; }
  else {
    state.assembliesErr = (r.data && r.data.error) || r.error || "unreadable";
    if (!Array.isArray(state.assemblies)) state.assemblies = null;
  }
  return r;
}
export async function loadAssembly(id){
  const key = String(id);
  const r = await getJSON("/api/assembly/" + encodeURIComponent(id), {timeout: 60000});
  const body = (r.ok && !(r.data && r.data.error)) ? asObj(r.data, "assembly") : r.data;
  const slot = state.assembly[key] || {};
  const bad = body && body.error && !(body.transcript || body.participants);
  if (r.ok && !bad){ slot.data = body; slot.at = r.at; slot.err = null; }
  else {
    slot.err = (body && body.error) || r.error || "unreadable";
    slot.errAt = r.at;
    if (r.status === 404) slot.data = null;
  }
  state.assembly[key] = slot;
  return r.ok && !bad ? {ok: true, data: body, at: r.at} : {ok: false, error: slot.err, data: body, at: r.at, status: r.status};
}
export function ciSlot(name){ return state.ci[String(name || "").toLowerCase()] || null; }
/* the colony, from /api/colony when we have it, else the copy embedded in /api/world */
export function colonyData(){
  if (state.colony) return state.colony;
  if (state.world && state.world.colony) return state.world.colony;
  return null;
}
export function colonyAgents(){
  const c = colonyData();
  return (c && Array.isArray(c.agents)) ? c.agents : [];
}

/* =================================================================== painting */

function cssEsc(v){ return String(v).replace(/["\\]/g, "\\$&"); }

/* Replace innerHTML only when it actually changed, keeping scroll, focus,
   caret and the window's scroll position — polling must not disturb reading. */
export function paint(el, html){
  if (!el) return false;
  if (el.__html === html) return false;
  const active = document.activeElement;
  const focusId = (active && el.contains(active) && active.id) ? active.id : null;
  let selA = null, selB = null;
  if (focusId && typeof active.selectionStart === "number"){
    try { selA = active.selectionStart; selB = active.selectionEnd; } catch (e) {}
  }
  const scrolls = [];
  el.querySelectorAll("[data-scroll]").forEach(n => {
    scrolls.push([n.getAttribute("data-scroll"), n.scrollTop, n.scrollLeft]);
  });
  const wy = window.scrollY, wx = window.scrollX;
  el.__html = html;
  el.innerHTML = html;
  scrolls.forEach(pair => {
    const n = el.querySelector('[data-scroll="' + cssEsc(pair[0]) + '"]');
    if (n){ n.scrollTop = pair[1]; n.scrollLeft = pair[2]; }
  });
  if (focusId){
    const f = el.querySelector("#" + cssEsc(focusId));
    if (f){
      try {
        f.focus({preventScroll: true});
        if (selA != null && typeof f.setSelectionRange === "function") f.setSelectionRange(selA, selB);
      } catch (e) {}
    }
  }
  if (window.scrollY !== wy || window.scrollX !== wx) window.scrollTo(wx, wy);
  return true;
}
/* after touching the DOM by hand, drop the memo so the next paint is honest */
export function invalidate(el){ if (el) el.__html = null; }

/* ===================================================================== router */

const VIEWS = {};
let cur = null;
const ctxRoot = () => document.getElementById("view");

export function register(name, mod){ VIEWS[name] = mod; }

export function parseRoute(){
  const raw = (location.hash || "").replace(/^#\/?/, "");
  const parts = raw.split("/").filter(x => x !== "")
    .map(x => { try { return decodeURIComponent(x); } catch (e){ return x; } });
  return {view: parts[0] || "world3d", params: parts.slice(1)};
}
export function nav(hash){
  if (location.hash === hash) routeTo();
  else location.hash = hash;
}
export function makeCtx(){
  return {
    root: ctxRoot(),
    route: cur ? cur.route : {view: "world", params: []},
    reload: function(){ if (cur && cur.mod && cur.mod.mount) cur.mod.mount(makeCtx()); },
  };
}
export function currentView(){ return cur ? cur.view : null; }
export function repaintCurrent(){
  if (cur && cur.mod && cur.mod.update){
    try { cur.mod.update(makeCtx()); } catch (e) { console.error(e); }
  }
}

function markNav(){
  const v = cur ? cur.view : "world";
  document.querySelectorAll("#nav a").forEach(a => {
    let on = a.dataset.view === v;
    if (v === "ci") on = a.dataset.view === "colony";
    a.classList.toggle("active", on);
  });
  const titles = {world3d: "world", world: "machine", colony: "colony", ci: "CI", intercom: "talk", assembly: "assemble", research: "research"};
  document.title = "MIST · " + (titles[v] || v) + (cur && cur.route.params[0] ? " · " + cur.route.params[0] : "");
}

export function routeTo(){
  const r = parseRoute();
  let mod = VIEWS[r.view];
  if (!mod){ r.view = "world"; mod = VIEWS.world; }
  if (cur && cur.mod && cur.mod.unmount){
    try { cur.mod.unmount(makeCtx()); } catch (e) { console.error(e); }
  }
  cur = {view: r.view, mod: mod, route: r};
  markNav();
  const ctx = makeCtx();
  try {
    if (mod.mount) mod.mount(ctx);
  } catch (e){
    console.error(e);
    ctx.root.__html = null;
    ctx.root.innerHTML = panel("view failed to render",
      errbox(String(e && e.stack || e)), {cls: "c12 bad"});
  }
  refreshChrome();
  window.scrollTo(0, 0);
}

/* ==================================================================== chrome */

function selfLine(){
  const w = state.world;
  if (!w || !w.self) return "";
  const sf = w.self;
  const gw = sf.gateway || {};
  const parts = [];
  parts.push(`<b>${esc(sf.name || "MIST")}</b>`);
  parts.push(`${dsh(sf.model)} <span class="sep">via</span> ${dsh(sf.provider)}`);
  parts.push(`host ${dsh(sf.host)}`);
  parts.push(gw && gw.pid ? chip("gateway pid " + esc(gw.pid), "on")
                          : chip("gateway down", "off"));
  if (has(sf.version)) parts.push(`v${esc(sf.version)}`);
  parts.push(`up ${esc(secsOf(sf.uptime_seconds))}`);
  return parts.join('<span class="sep"> · </span>');
}

export function refreshChrome(){
  const pulse = document.getElementById("pulse");
  const sys = document.getElementById("sys");
  const band = document.getElementById("band");
  const foot = document.getElementById("footnote");
  const w = state.world;
  const now = Date.now();
  const age = state.worldAt ? now - state.worldAt : null;
  let stateCls = "", stateTxt = "connecting…";
  if (state.worldErr){
    stateCls = "dead";
    stateTxt = "console cannot read itself: " + state.worldErr;
  } else if (age != null && age > STALE_AFTER_MS){
    stateCls = "stale";
    stateTxt = "stale · last good " + secsOf(age / 1000) + " ago";
  } else if (age != null){
    stateTxt = "live · " + secsOf(age / 1000) + " ago";
  }
  if (pulse) pulse.className = "pulse " + stateCls;

  if (sys){
    const w2 = state.world;
    const g = (w2 && w2.self && w2.self.gateway) || {};
    const errs = (w2 && Array.isArray(w2.errors)) ? w2.errors.length : 0;
    let html = selfLine();
    html += `<span class="sep"> · </span>generated ${esc(w2 ? (w2.generated || "—") : "—")}`;
    html += `<span class="sep"> · </span><span class="${stateCls === "dead" ? "badc" : stateCls === "stale" ? "warnc" : "ok"}">${esc(stateTxt)}</span>`;
    if (errs) html += `<span class="sep"> · </span>${chip(errs + " source error" + (errs === 1 ? "" : "s"), "off")}`;
    if (g && g.last_exit && g.last_exit !== "0") html += `<span class="sep"> · </span>${chip("last exit " + esc(g.last_exit), "warnb")}`;
    if (state.busy) html += `<span class="sep"> · </span>${chip("POLL PAUSED · " + esc(state.spendNote || "live call in flight"), "warnb")}`;
    paint(sys, html);
  }

  if (band){
    const msgs = [];
    if (state.worldErr) msgs.push({cls: "", html: `<b>world unreachable.</b> ${esc(state.worldErr)}. Showing the last good reading (${esc(state.worldAt ? agoOf(state.worldAt / 1000) : "none")}).`});
    else if (age != null && age > STALE_AFTER_MS) msgs.push({cls: "warn", html: `<b>stale.</b> last good reading ${esc(secsOf(age / 1000))} ago.`});
    if (w && w.errors && w.errors.length) msgs.push({cls: "warn", html: `<b>${w.errors.length} source(s) failed:</b> ${esc(w.errors.join(" · "))}`});
    if (state.busy) msgs.push({cls: "warn", html: `<b>polling paused</b> — a live model call is in flight (${esc(state.spendNote || "working")}). Panels hold their last reading.`});
    band.className = "band" + (msgs.length && msgs[0].cls ? " " + msgs[0].cls : "");
    const html = msgs.map(m => `<div class="${m.cls}">${m.html}</div>`).join("");
    if (band.__html !== html){ band.__html = html; band.innerHTML = html; }
  }

  if (foot){
    foot.innerHTML = `polling /api/world ${state.polls ? "" : ""}every ${POLL_MS / 1000}s · `
      + `<b>${num(state.polls)}</b> poll(s) · last poll ${esc(state.lastPollAt ? agoOf(state.lastPollAt / 1000) : "—")}`
      + ` · colony ${state.colony ? esc("tick " + (state.colony.tick != null ? state.colony.tick : "—")) : "not read"}`;
  }
}

/* ===================================================================== polling */

export async function pollOnce(){
  if (state.busy > 0 || document.hidden) return;
  const jobs = [loadWorld()];
  const v = cur ? cur.view : null;
  if (v === "colony") jobs.push(loadColony());
  if (v === "ci" && cur.route.params[0]) jobs.push(loadCI(cur.route.params[0]));
  try { await Promise.all(jobs); } catch (e) { console.error(e); }
  refreshChrome();
  if (state.busy > 0) return;            /* a spend started mid-poll: don't repaint under it */
  if (cur && cur.mod && cur.mod.update){
    try { cur.mod.update(makeCtx()); } catch (e) { console.error(e); }
  }
}

/* ====================================================================== boot */

import * as worldView from "./views/world.js";
import * as world3dView from "./views/world3d.js";
import * as colonyView from "./views/colony.js";
import * as ciView from "./views/ci.js";
import * as intercomView from "./views/intercom.js";
import * as assemblyView from "./views/assembly.js";
import * as researchView from "./views/research.js";

register("world", worldView);
register("world3d", world3dView);
register("colony", colonyView);
register("ci", ciView);
register("intercom", intercomView);
register("assembly", assemblyView);
register("research", researchView);

function boot(){
  window.addEventListener("hashchange", routeTo);
  routeTo();
  loadWorld().then(() => { refreshChrome(); repaintCurrent(); });
  loadColony().then(() => { refreshChrome(); repaintCurrent(); });
  loadAssemblies().then(() => { refreshChrome(); if (cur && cur.view === "assembly") repaintCurrent(); });
  setInterval(pollOnce, POLL_MS);
  setInterval(refreshChrome, 1000);
}
boot();
