/* ASSEMBLE — meetings, dinners and townhalls the colony holds with itself.
 * POST /api/assembly            : run one (each speech is ONE live model call)
 * GET  /api/assemblies          : the past ones
 * GET  /api/assembly/<id>       : one, whole
 */
import {
  state, paint, esc, num, msOf, secsOf, clockOf, agoOf, chip, panel, table,
  empty, note, errbox, hyper, loadAssemblies, loadAssembly, loadColony,
  colonyAgents, colonyData, postJSON, beginSpend, endSpend, ASSEMBLY_TIMEOUT_MS,
} from "../app.js";
import { sigil } from "../being.js";

const KINDS = ["meeting", "dinner", "townhall"];
const DEFAULTS = {townhall: 1, dinner: 1, meeting: 2};
const BLURB = {
  townhall: "every CI answers the topic, one round, no cross-talk",
  meeting:  "each CI speaks in turn; later speakers hear what came before (debate)",
  dinner:   "loose conversation — no agenda, each CI speaks once, in character",
};

let st = {kind: "meeting", topic: "", rounds: null, picked: {}, running: false, err: null, phase: ""};
let ctxRef = null;
let ticker = null;

export function mount(ctx){
  ctxRef = ctx;
  ctx.root.addEventListener("click", onClick);
  ctx.root.addEventListener("change", onChange);
  ctx.root.addEventListener("input", onInput);
  if (!colonyAgents().length && !state.colony) loadColony().then(() => { if (ctxRef === ctx) render(ctx); });
  if (!state.assemblies) loadAssemblies().then(() => { if (ctxRef === ctx) render(ctx); });
  const id = ctx.route.params[0];
  if (id) loadAssembly(id).then(() => { if (ctxRef === ctx) render(ctx); });
  render(ctx);
}
export function unmount(ctx){
  if (ctx && ctx.root){
    ctx.root.removeEventListener("click", onClick);
    ctx.root.removeEventListener("change", onChange);
    ctx.root.removeEventListener("input", onInput);
  }
  stopTicker();
  ctxRef = null;
}

function render(ctx){
  const id = ctx.route.params[0];
  if (id) paint(ctx.root, detailPanel(id) + pastPanel(id));
  else paint(ctx.root, formPanel() + pastPanel(null));
  syncForm();
}

/* ------------------------------------------------------------------- form */

function selectedNames(){
  return colonyAgents().filter(a => st.picked[a.name]).map(a => a.name);
}
function effRounds(){
  const r = Number(st.rounds);
  const v = (isFinite(r) && r > 0) ? Math.min(3, Math.max(1, Math.round(r))) : DEFAULTS[st.kind];
  return v;
}

function formPanel(){
  const agents = colonyAgents();
  const c = colonyData();
  const tiers = (c && c.models) || {};
  const pick = agents.length
    ? `<div class="picklist" data-scroll="asm-cis">` + agents.map(a =>
        `<label title="${esc(a.domain)}" style="align-items:center">` +
        sigil(a, 22) +
        `<input type="checkbox" data-ci="${esc(a.name)}" ${st.picked[a.name] ? "checked" : ""}> ` +
        `<b>${esc(a.name)}</b> <span class="tier-${esc(a.tier)}">${esc(a.tier)}</span>` +
        (a.status !== "active" ? ` <span class="dim2">(${esc(a.status || "?")})</span>` : "") +
        `</label>`).join("") + `</div>`
    : (state.colonyErr ? errbox(state.colonyErr) : empty("the colony roster is not readable yet"));

  const body =
    `<div class="note">Every CI in the room receives the roster’s current work and cautious, evidence-based affect cues; no private feelings are assumed.</div>` +
    `<div class="formgrid">` +
      `<div><label class="fl">kind</label>` +
        `<select id="asm-kind">` + KINDS.map(k =>
          `<option value="${k}" ${st.kind === k ? "selected" : ""}>${k} — ${esc(BLURB[k])}</option>`).join("") +
        `</select></div>` +
      `<div><label class="fl">rounds (1–3)</label>` +
        `<input type="text" id="asm-rounds" value="${effRounds()}" style="width:70px">` +
        `<div class="hint">default for ${esc(st.kind)}: ${DEFAULTS[st.kind]}</div></div>` +
    `</div>` +
    `<label class="fl">topic</label>` +
    `<textarea id="asm-topic" rows="2" placeholder="what should they take up?">${esc(st.topic)}</textarea>` +
    `<label class="fl">who attends · ${agents.length} CI(s) available</label>` +
    pick +
    `<div class="actions">` +
      `<button class="small" data-act="all">select all</button>` +
      `<button class="small" data-act="none">clear</button>` +
      (Object.keys(tiers).length ? `<span class="hint">tier models: ${esc(["reflex","worker","specialist","architect"].filter(k => tiers[k]).map(k => k + "=" + tiers[k]).join(" · "))}</span>` : "") +
    `</div>` +
    `<div class="cost" id="asm-cost">—</div>` +
    (st.err ? errbox(st.err) : "") +
    (st.running ? `<div class="cost" id="asm-run">running… <span id="asm-elapsed">0s</span> elapsed. One live model call per speech; polling is paused while it works.</div>` : "") +
    `<div class="actions">` +
      `<button class="primary" id="asm-run-btn" data-act="run">run ${esc(st.kind)}</button>` +
      `<span class="hint">${esc(BLURB[st.kind])}</span>` +
    `</div>`;
  return panel("convene", body, {cls: "c5", meta: "spends tokens — one call per speech"});
}

function syncForm(){
  const cost = document.getElementById("asm-cost");
  const btn = document.getElementById("asm-run-btn");
  if (!cost) return;
  const n = selectedNames().length;
  const r = effRounds();
  const calls = n * r;
  if (st.running){
    cost.innerHTML = `<b>running.</b> ${n} CI(s) × ${r} round(s) = <b>${calls}</b> live model call(s) in flight. A meeting of ${n} × ${r} can take a few minutes.`;
  } else if (!n){
    cost.innerHTML = `select at least one CI. Each speech is <b>one live model call</b> on that CI's tier model.`;
  } else {
    cost.innerHTML = `This will run <b>${n} CI(s) × ${r} round(s) = ${calls} live model call(s)</b> and spend tokens. ` +
      `It cannot be undone; the transcript is saved either way.`;
  }
  const rounds = document.getElementById("asm-rounds");
  if (rounds && String(rounds.value) !== String(r) && document.activeElement !== rounds) rounds.value = String(r);
  if (btn){
    btn.disabled = st.running || !n || !st.topic.trim();
    btn.textContent = st.running ? "running…" : ("run " + st.kind + (calls ? " · " + calls + " call(s)" : ""));
  }
}

/* ------------------------------------------------------------------- detail */

function detailPanel(id){
  const slot = state.assembly[String(id)] || {};
  const a = slot.data;
  if (!a || a.error){
    return panel("assembly · " + id,
      (slot.err ? errbox(slot.err) : (a && a.error ? errbox(a.error) : note("opening assembly " + id + "…"))) +
      `<div class="actions">${hyper("#/assembly", "← all assemblies")}</div>`,
      {cls: "c8 " + (slot.err || (a && a.error) ? "bad" : "")});
  }
  const pmap = {};
  (a.participants || []).forEach(p => { pmap[p.name] = p; });
  const seats = (a.participants || []).map(p =>
    `<div class="seat">${sigil(p, 64)}` +
    `<span class="who">${hyper("#/ci/" + encodeURIComponent(p.name), p.name)}</span>` +
    `<span class="what">${esc(p.tier)} · ${esc(p.domain || "—")}</span>` +
    (p.affect ? `<span class="what" title="${esc((p.affect_cues||[]).join('; '))}">observed affect · ${esc(p.affect)}</span>` : "") +
    (p.work ? `<span class="what" title="${esc(p.work)}">${esc(String(p.work).slice(0,58))}</span>` : "") + `</div>`).join("");

  const tr = (a.transcript || []);
  let lastRound = null;
  const turnHTML = tr.map(t => {
    let head = "";
    if (t.round !== lastRound){ lastRound = t.round; head = `<div class="roundbar">round ${esc(t.round)}</div>`; }
    const p = pmap[t.name] || {name: t.name, tier: t.tier, domain: ""};
    const delivery=t.text?esc(t.text):`<span class="bad">No complete reply was published${t.error?": "+esc(t.error):"."}</span>`;
    const quality=t.recovered?" · recovered after retry":(t.retries?" · retry failed":"");
    return head + `<div class="say">${sigil(p, 42)}<div class="saybody">` +
      `<div class="saywho">${esc(t.name)} <span class="meta">${esc(t.tier)} · ${esc(t.model || "?")} · ${esc(msOf(t.ms))} · ${num(t.tokens)} tok · ${esc(clockOf(t.ts))}${esc(quality)}</span></div>` +
      `<div class="saytext">${delivery}</div></div></div>`;
  }).join("");

  const spend = a.spend || {};
  const body =
    `<div class="rowline" style="margin-bottom:6px">` +
      chip(esc(a.kind), "on") + chip("rounds " + esc(a.rounds)) +
      chip(esc(a.status || "?")) +
      chip("created " + esc(clockOf(a.created)) + " · " + esc(agoOf(a.created))) +
      chip(num((a.cis || []).length) + " CI(s)") +
      chip(num(spend.calls) + " calls") + chip(num(spend.tokens) + " tokens") +
      `<span class="dim2">id ${esc(a.id)}</span>` +
      hyper("#/assembly", "← all", "hint") +
    `</div>` +
    `<div class="note" style="margin-bottom:4px">topic</div>` +
    `<div style="color:var(--ink2);margin-bottom:8px">${esc(a.topic || "—")}</div>` +
    (seats ? `<div class="roomseat">${seats}</div>` : "") +
    (a.closing ? `<div class="note">closing</div><div style="color:var(--ink2);margin-bottom:8px">${esc(a.closing)}</div>` : "") +
    `<div class="note" style="margin-bottom:4px">transcript · ${tr.length} speech(es)</div>` +
    (tr.length ? `<div class="scrolly tall" data-scroll="asm-tr">${turnHTML}</div>`
               : empty("no speeches recorded"));
  return panel("assembly · " + esc(a.kind || id), body,
    {cls: "c8", meta: slot.err ? chip("stale/err", "off") : ""});
}

/* --------------------------------------------------------------------- list */

function pastPanel(activeId){
  const list = state.assemblies;
  const rows = (Array.isArray(list) ? list : []).map(a => [
    hyper("#/assembly/" + encodeURIComponent(a.id), String(a.id), String(a.id) === String(activeId || "") ? "chip on" : ""),
    chip(esc(a.kind || "?")),
    `<span class="wrap">${esc(String(a.topic || "").slice(0, 70))}</span>`,
    esc(clockOf(a.created)),
    esc(agoOf(a.created)),
    num(Array.isArray(a.cis) ? a.cis.length : a.cis),
    num(a.rounds),
    esc(a.status || "—"),
    num(a.speakers),
    num(a.transcript_len),
  ]);
  const body =
    (state.assembliesErr ? errbox(state.assembliesErr) : "") +
    (Array.isArray(list)
      ? table(["id", "kind", "topic", "created", "when", "cis", "rounds", "status", "spk", "len"], rows,
          {scroll: "tall", key: "asm-list", empty: "the colony has not assembled yet"})
      : (state.assembliesErr ? "" : note("reading past assemblies…")));
  return panel(`past assemblies · ${Array.isArray(list) ? list.length : "—"}`, body,
    {cls: activeId ? "c4" : "c7", meta: "newest first"});
}

/* ------------------------------------------------------------------ actions */

function onClick(ev){
  const btn = ev.target.closest("[data-act]");
  if (!btn) return;
  const a = btn.getAttribute("data-act");
  if (a === "all"){
    colonyAgents().forEach(x => { st.picked[x.name] = true; });
    render(ctxRef);
  } else if (a === "none"){
    st.picked = {};
    render(ctxRef);
  } else if (a === "run"){
    run();
  }
}
function onChange(ev){
  const t = ev.target;
  if (!t) return;
  if (t.id === "asm-kind"){
    st.kind = t.value;
    st.rounds = DEFAULTS[st.kind];
    render(ctxRef);
  } else if (t.id === "asm-rounds"){
    st.rounds = Number(t.value) || DEFAULTS[st.kind];
    syncForm();
  } else if (t.dataset && t.dataset.ci && t.type === "checkbox"){
    st.picked[t.dataset.ci] = t.checked;
    syncForm();
  }
}
function onInput(ev){
  const t = ev.target;
  if (!t) return;
  if (t.id === "asm-topic"){ st.topic = t.value; syncForm(); }
  else if (t.id === "asm-rounds"){ st.rounds = Number(t.value) || null; syncForm(); }
}

async function run(){
  const cis = selectedNames();
  const topic = st.topic.trim();
  const rounds = effRounds();
  if (!cis.length || !topic || st.running) return;
  st.running = true; st.err = null; st.phase = "";
  render(ctxRef);
  startTicker();
  beginSpend("convening a " + st.kind);
  const r = await postJSON("/api/assembly",
    {kind: st.kind, topic: topic, cis: cis, rounds: rounds},
    {timeout: ASSEMBLY_TIMEOUT_MS});
  endSpend();
  stopTicker();
  st.running = false;
  let a = r.data;
  if (a && a.assembly && typeof a.assembly === "object" && a.id == null) a = a.assembly;
  if (r.ok && a && a.id != null){
    state.assembly[String(a.id)] = {data: a, at: Date.now(), err: null};
    loadAssemblies();
    location.hash = "#/assembly/" + encodeURIComponent(a.id);
    return;
  }
  st.err = (a && a.error) || r.error || "the assembly failed";
  render(ctxRef);
}

function startTicker(){
  stopTicker();
  const t0 = Date.now();
  ticker = setInterval(() => {
    const el = document.getElementById("asm-elapsed");
    if (el) el.textContent = secsOf((Date.now() - t0) / 1000);
  }, 500);
}
function stopTicker(){ if (ticker){ clearInterval(ticker); ticker = null; } }
