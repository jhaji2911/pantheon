/* CI DRILL-DOWN — one CI opened up: the brain.
 * GET /api/ci/<name> : agent, tier spec, identity, memory, notebook, submissions,
 * instruments (audit trail), ledger, usage, events, doing, lineage, thread.
 * GET /api/ci/<name>/note?path=  : one notebook file.
 */
import {
  paint, esc, dsh, num, f2, clockOf, timeOf, agoOf, msOf,
  chip, kv, panel, table, empty, note, errbox,
  hyper, loadCI, ciSlot, sourceTag, getJSON, READ_TIMEOUT_MS,
} from "../app.js";
import { sigil, firstPerson, traits, talents } from "../being.js";

let local = {name: null, openPath: null, note: null, noteErr: null, noteBusy: false, dirty: 0, selectedNode: null};
let ctxRef = null;

export function mount(ctx){
  const name = ctx.route.params[0];
  if (!name){
    paint(ctx.root, panel("a CI", note("no CI named in the route — pick one from the colony roster.") +
      `<div class="actions">${hyper("#/colony", "open the colony →")}</div>`, {cls: "c12"}));
    return;
  }
  const same = local.name && local.name.toLowerCase() === String(name).toLowerCase();
  if (!same) local = {name: name, openPath: null, note: null, noteErr: null, noteBusy: false, dirty: 0, selectedNode: null};
  ctxRef = ctx;
  ctx.root.addEventListener("click", onClick);
  ctx.root.addEventListener("keydown", onKey);
  loadCI(name).then(() => { if (current(ctx, name)) render(ctx); });
  loadMindLog(name).then(() => { if (current(ctx, name)) render(ctx); });
  render(ctx);
}

async function loadMindLog(name){
  try {
    const r = await getJSON("/api/pantheon/minds/log?limit=25&name=" + encodeURIComponent(name), {timeout: READ_TIMEOUT_MS});
    if (local.name === name) local.mind = r && r.ok ? r.data : {error: (r && r.error) || "unavailable"};
  } catch (e) { if (local.name === name) local.mind = {error: String(e)}; }
}
export function update(ctx){ render(ctx); }
export function unmount(ctx){
  if (ctx && ctx.root){ ctx.root.removeEventListener("click", onClick); ctx.root.removeEventListener("keydown", onKey); }
  ctxRef = null;
}

function current(ctx, name){
  return ctx.route.params[0] && String(ctx.route.params[0]).toLowerCase() === String(name).toLowerCase();
}

function render(ctx){
  const name = ctx.route.params[0];
  if (!name) return;
  const slot = ciSlot(name);
  const d = slot && slot.data;
  if (!d){
    paint(ctx.root, panel("CI · " + name,
      (slot && slot.err ? errbox(slot.err) : note("opening " + name + "…")),
      {cls: "c12 " + ((slot && slot.err) ? "bad" : "")}));
    return;
  }
  paint(ctx.root, [
    headPanel(name, d, slot),
    cognitiveGraphPanel(d),
    pantheonMindPanel(),
    identityPanel(d),
    tierPanel(d),
    doingPanel(d),
    memoryPanel(d),
    notebookPanel(name, d),
    instrumentsPanel(d),
    submissionsPanel(d),
    ledgerPanel(d),
    usagePanel(d),
    eventsPanel(d),
    lineagePanel(d),
    threadPanel(name, d),
  ].filter(Boolean).join(""));
}

/* --------------------------------------------------------------- sections */

function headPanel(name, d, slot){
  const a = d.agent || {};
  const meta = slot && slot.err ? sourceTag(slot.at, slot.err, Date.now()) : sourceTag(slot.at, null, Date.now());
  const hero =
    `<div class="mindhero">` +
      sigil(a, 108) +
      `<div style="flex:1;min-width:240px">` +
        `<div class="mindname">${esc(a.name || name)}</div>` +
        `<div class="mindmeta">${esc(a.tier)} · attuned to ${esc(a.domain)} · generation ${num(a.generation)} · ${num(Math.round(a.credits))} credits · fitness ${f2(a.fitness)}</div>` +
        `<div class="btraits" style="justify-content:flex-start;margin-top:6px">${traits(a).map(t => `<i>${esc(t)}</i>`).join("")}</div>` +
        (d.affect ? `<div class="mindmeta" style="margin-top:6px">observed affect · ${esc(d.affect.label)} <span title="${esc(d.affect.cues.join('; '))}">ⓘ</span></div>` : "") +
        (firstPerson(d.identity) ? `<div class="mindline" style="margin-top:9px">${esc(firstPerson(d.identity))}</div>` : "") +
      `</div>` +
    `</div>`;
  const body = hero +
    `<div class="actions" style="margin-top:12px">` +
      hyper("#/intercom/" + encodeURIComponent(a.name || name), "talk to " + (a.name || name) + " →", "chip") +
      hyper("#/colony", "← colony", "hint") +
      `<button class="small" data-act="refresh">refresh now</button>` +
      `<span class="hint">talking runs one live model call and spends tokens.</span>` +
    `</div>` +
    `<div class="split2" style="margin-top:8px"><div>` +
      kv("credits", `<b>${num(Math.round(a.credits))}</b>`) +
      kv("fitness", f2(a.fitness)) +
      kv("tasks verified / attempted", `${num(a.tasks_verified)} / ${num(a.tasks_attempted)}`) +
      kv("failures streak", a.failures_streak ? `<span class="badc">${num(a.failures_streak)}</span>` : "0") +
      kv("hibernating since", a.hibernating_since ? esc(clockOf(a.hibernating_since)) : "—") +
    `</div><div>` +
      kv("born tick", num(a.born_tick)) +
      kv("last tick", num(a.last_tick)) +
      kv("cadence", dsh(a.cadence)) +
      kv("phase", dsh(a.phase)) +
      kv("session", `<span class="dim2">${dsh(a.session_id)}</span>`) +
    `</div></div>`;
  return panel("CI", body, {cls: "c12", meta});
}

function cognitiveNodes(d){
  const a=d.agent||{},trace=d.prompt_trace||{},nodes=[];
  const promptMemories=new Set(trace.memory_ids||[]);
  if(d.doing){
    nodes.push({key:"task",kind:"work",glyph:"W",label:"active work",why:"This is the CI's current claimed task; task_block inserts it into the next reasoning prompt.",detail:`Task ${d.doing.task_id} · ${d.doing.domain} · ${d.doing.question||""}`});
  }
  (d.memory||[]).slice(0,3).forEach(m=>nodes.push({
    key:"memory:"+m.id,kind:"memory",glyph:"M",label:`${m.kind||"memory"} · t${m.tick}`,
    why:promptMemories.has(m.id)?`Selected by the prompt builder's recency recall (one of the latest ${trace.memory_recall_limit||6} memories). This proves it was supplied as context, not that a hidden neuron attended to it.`:"Stored in the CI's durable memory; not in the latest prompt recall set.",
    detail:m.text||"(empty memory)",
  }));
  (d.instruments||[]).slice(0,2).forEach((i,n)=>nodes.push({
    key:"instrument:"+i.tick+":"+n,kind:"tool",glyph:"T",label:i.name||"instrument",
    why:"Recorded tool execution from the colony audit trail; the result is independently inspectable.",
    detail:`tick ${i.tick} · args ${typeof i.args==="string"?i.args:JSON.stringify(i.args)} · result ${typeof i.result==="string"?i.result:JSON.stringify(i.result)}`,
  }));
  (d.submissions||[]).slice(0,1).forEach(s=>nodes.push({
    key:"submission:"+s.id,kind:"work",glyph:"✓",label:s.verified?"verified":"submission",
    why:s.verified?"Independent verifier accepted this submission.":"Submission is recorded but was not independently verified.",
    detail:`task ${s.task_id} · ${s.detail||s.answer||""}`,
  }));
  const ciName=String(a.name||"").toLowerCase();
  for(const interaction of (d.interactions||[])){
    for(const peer of interaction.peers||[]){
      if(nodes.filter(n=>n.kind==="peer").length>=2)break;
      const own=(interaction.transcript||[]).filter(t=>String(t.name).toLowerCase()===ciName).map(t=>t.text).join("\n");
      const theirs=(interaction.transcript||[]).filter(t=>String(t.name).toLowerCase()===String(peer).toLowerCase()).map(t=>t.text).join("\n");
      nodes.push({key:"peer:"+interaction.id+":"+peer,kind:"peer",glyph:"↔",label:"with "+peer,
        peer,interaction,
        why:`Saved ${interaction.kind||"conversation"} #${interaction.id} included both CIs; this edge comes from its participant list.`,
        detail:`Topic: ${interaction.topic||"(no topic)"}\n${a.name}: ${own||"no recorded speech"}\n${peer}: ${theirs||"no recorded speech"}`});
    }
    if(nodes.filter(n=>n.kind==="peer").length>=2)break;
  }
  return nodes;
}

function cognitiveGraphPanel(d){
  const a=d.agent||{},nodes=cognitiveNodes(d),cx=300,cy=130,rx=236,ry=93;
  const positioned=nodes.map((n,i)=>{
    const angle=(2*Math.PI*i/Math.max(1,nodes.length))-Math.PI/2;
    return {...n,x:cx+Math.cos(angle)*rx,y:cy+Math.sin(angle)*ry};
  });
  const selected=positioned.find(n=>n.key===local.selectedNode);
  const edges=positioned.map(n=>`<line class="cog-edge ${n.kind}" x1="${cx}" y1="${cy}" x2="${n.x.toFixed(1)}" y2="${n.y.toFixed(1)}"/>`).join("");
  const nodesSvg=positioned.map(n=>`<g class="cog-node ${n.kind}${n.peer?" linked":""}" data-cog-node="${esc(n.key)}" ${n.peer?`data-peer="${esc(n.peer)}"`:""} tabindex="0" role="button" aria-label="${esc(n.label)}">
    <title>${esc(n.why)}</title><circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="17"/><text x="${n.x.toFixed(1)}" y="${(n.y+4).toFixed(1)}">${esc(n.glyph)}</text>
    <text class="cog-label" x="${n.x.toFixed(1)}" y="${(n.y+31).toFixed(1)}">${esc(String(n.label).slice(0,20))}</text></g>`).join("");
  const center=`<circle class="cog-self" cx="${cx}" cy="${cy}" r="27"/><text class="cog-selfmark" x="${cx}" y="${cy+4}">CI</text><text class="cog-center-label" x="${cx}" y="${cy+43}">${esc(a.name||"CI")}</text>`;
  const detail=selected?`<div class="cog-detail"><div class="cog-why"><b>Why this node is active</b> · ${esc(selected.why)}</div><pre>${esc(selected.detail)}</pre>`+
    (selected.peer?`<button class="small" data-mind-jump="${esc(selected.peer)}">jump to ${esc(selected.peer)}’s brain →</button>`:"")+`</div>`:
    `<div class="note">Select a node to inspect its source and why it appears here. Peer nodes open that CI’s brain.</div>`;
  const body=`<div class="cog-caption">Evidence graph · recorded prompt inputs, work, tools, and saved social edges. These are not literal neural activations.</div>`+
    `<svg class="cog-graph" viewBox="0 0 600 280" role="img" aria-label="${esc(a.name||"CI")} evidence graph">${edges}${center}${nodesSvg}</svg>`+
    `<div class="cog-legend"><span>● focus/context</span><span>● memory</span><span>● tool/work</span><span>● peer interaction</span></div>`+detail;
  return panel("brain map · evidence trace",body,{cls:"c12",meta:`${nodes.length} source node(s) · affect ${esc((d.affect||{}).label||"unknown")}`});
}

function identityPanel(d){
  const id = d.identity || {};
  const inst = id.instruments || [];
  const body =
    kv("name", dsh(id.name)) +
    kv("tier", `<span class="tier-${esc(id.tier)}">${dsh(id.tier)}</span>`) +
    kv("domain", dsh(id.domain)) +
    kv("generation", num(id.generation)) +
    `<div style="margin-top:7px"><div class="note">world note — how it understands its place</div>` +
    `<div class="scrolly short" data-scroll="worldnote"><pre>${esc(id.world_note || "(none)")}</pre></div></div>` +
    `<div style="margin-top:7px"><div class="note">instruments it may hold</div>` +
    (inst.length ? inst.map(i => chip(esc(typeof i === "string" ? i : (i.name || JSON.stringify(i))))).join("")
                 : `<span class="dim">—</span>`) + `</div>`;
  return panel("identity", body, {cls: "c4"});
}

function tierPanel(d){
  const t = d.tier || {};
  const may = t.may || [];
  const body =
    kv("level", dsh(t.level)) +
    kv("model", esc(t.model || "—")) +
    kv("max tokens", num(t.max_tokens)) +
    kv("tool rounds", num(t.tool_rounds)) +
    kv("temperature", t.temperature == null ? "—" : f2(t.temperature, 2)) +
    `<div style="margin-top:7px"><div class="note">permissions — what this tier may do</div>` +
    (may.length ? may.map(m => chip(esc(typeof m === "string" ? m : JSON.stringify(m)), "on")).join("")
                : `<span class="dim">—</span>`) + `</div>` +
    `<div style="margin-top:9px"><div class="note">talents — its reach</div>` +
    talents(t) + `</div>`;
  return panel("tier spec & permissions", body, {cls: "c4"});
}

function doingPanel(d){
  const w = d.doing;
  const usage = (d.usage || [])[0];
  let body;
  if (w){
    body =
      kv("task", chip("t" + esc(w.task_id), "on")) +
      kv("domain", dsh(w.domain)) +
      kv("difficulty", num(w.difficulty)) +
      kv("reward", num(w.reward)) +
      kv("claimed at tick", num(w.claimed_tick)) +
      `<div style="margin-top:6px"><div class="note">the question in front of it</div>` +
      `<div class="scrolly short" data-scroll="doingq"><pre>${esc(w.question || "")}</pre></div></div>`;
  } else {
    body = empty("idle — holding no claim");
  }
  body += `<div style="margin-top:7px"><div class="note">last model call</div>` +
    (usage
      ? kv("at", esc(timeOf(usage.ts)) + " " + chip(esc(agoOf(usage.ts)))) +
        kv("model", esc(usage.model || "—")) +
        kv("tier", esc(usage.tier || "—")) +
        kv("latency", esc(msOf(usage.ms))) +
        kv("tokens", num(usage.tokens)) +
        kv("ok", usage.ok === false ? chip("failed", "off") : chip("ok", "on"))
      : `<span class="dim">—</span>`) + `</div>`;
  return panel("doing right now", body, {cls: "c4"});
}

function pantheonMindPanel(){
  const m = local.mind;
  if (!m) return panel("Pantheon mind", note("loading decisions…"), {cls: "c12"});
  if (m.error) return panel("Pantheon mind", errbox(m.error), {cls: "c12 bad"});
  const st = m.status || {};
  const log = m.log || [];
  const rows = log.map(e => `<div class="card">
    <div class="crole">${chip(esc(timeOf(e.ts)) + " · " + esc(agoOf(e.ts)))}${chip(esc(e.kind || "moment"))}${e.action ? chip(esc(e.action.kind)) : chip("no decision")}${chip(esc(e.locality || "cloud") + " · " + esc(e.model || ""))}` +
    `${chip(num(e.tokens) + " tok")}${e.ok ? "" : `<span class="badc">${esc(e.error || "failed")}</span>`}</div>
    ${e.thought ? `<div class="mindline" style="margin-top:4px">${esc(e.thought)}</div>` : ""}
    ${e.goal ? `<div class="hint">goal · ${esc(e.goal)}</div>` : ""}
    ${e.action ? `<div style="margin-top:3px;color:var(--ink2)">${esc(JSON.stringify(e.action))}</div>` : ""}
    ${e.outcome ? `<div class="${String(e.outcome).startsWith("failed") ? "badc" : "hint"}">→ ${esc(e.outcome)}</div>` : ""}
    <details style="margin-top:4px"><summary class="hint">what it perceived</summary>
      <pre style="white-space:pre-wrap;font-size:11px">${esc(JSON.stringify(e.observation, null, 1))}</pre></details>
  </div>`).join("");
  const eps = (m.episodes || []).slice().reverse().map(e =>
    `<div class="card"><div class="crole">${chip(esc(e.kind))}${chip("salience " + f2(e.salience))}</div>` +
    `<div style="margin-top:3px;color:var(--ink2)">${esc(e.text)}</div></div>`).join("");
  const lf = m.life || {};
  const needs = lf.needs ? Object.entries(lf.needs).map(([k, v]) =>
    `<div style="display:flex;gap:8px;align-items:center"><span class="hint" style="width:72px">${esc(k)}</span>` +
    `<div style="flex:1;height:6px;background:var(--line,#2a3438);border-radius:3px"><div style="width:${Math.round(v * 100)}%;height:6px;border-radius:3px;background:${v < 0.35 ? "#c96f5a" : "#6cbfa6"}"></div></div>` +
    `<span class="hint" style="width:34px;text-align:right">${f2(v)}</span></div>`).join("") : empty("no needs recorded yet");
  const plan = lf.plan ? `<div class="mindline">${esc(lf.plan.intent || "")}</div>` + lf.plan.blocks.map(b =>
    `<div class="hint">${esc(String(b.from).padStart(2, "0"))}–${esc(b.to)}h · ${esc(b.place)} · ${esc(b.doing)}${b.with ? " · with " + esc(b.with) : ""}</div>`).join("")
    : empty("no plan for today yet");
  const rels = (lf.relations || []).length ? (lf.relations || []).map(r =>
    `<div class="hint">${hyper("#/ci/" + encodeURIComponent(r.name), esc(r.name))} · regard ${f2(r.affinity)} · ${num(r.familiarity)} exchange(s)${r.note ? " · " + esc(r.note) : ""}</div>`).join("")
    : empty("knows no one yet");
  const lifeRow = `<div class="split2" style="margin-bottom:10px"><div><b>needs</b>${needs}</div>` +
    `<div><b>today</b>${plan}<div style="margin-top:8px"><b>people</b>${rels}</div></div></div>`;
  const meta = `cloud ${esc(st.cloud_model || "")} · ${num(st.cloud_tokens_24h)} / ${num(st.daily_token_cap)} cloud tokens 24h · local via inferN ${num(st.local_tokens_24h)}` +
    (st.last_error ? ` · last error: ${esc(st.last_error)}` : "");
  return panel(`Pantheon mind · ${log.length} decision(s)`,
    lifeRow + `<div class="split2"><div>${log.length ? `<div class="scrolly tall"><div class="stack">${rows}</div></div>`
       : empty("no decisions yet — press B in Pantheon to turn minds on")}</div>` +
    `<div>${eps ? `<div class="scrolly tall"><div class="stack">${eps}</div></div>` : empty("no episodic memory yet")}</div></div>`,
    {cls: "c12", meta});
}

function memoryPanel(d){
  const mem = d.memory || [];
  const cards = mem.map(m => `<div class="card">
    <div class="crole">${chip("tick " + esc(m.tick))}${m.kind ? chip(esc(m.kind)) : ""}` +
    `${m.salience != null ? chip("salience " + esc(m.salience)) : ""}` +
    `${m.origin_agent_id != null ? chip("from CI " + esc(m.origin_agent_id)) : ""}</div>
    <div style="margin-top:3px;color:var(--ink2)">${esc(m.text || "")}</div>
  </div>`).join("");
  return panel(`memory · ${mem.length}`,
    mem.length ? `<div class="scrolly tall" data-scroll="cimem"><div class="stack">${cards}</div></div>`
               : empty("nothing in memory"),
    {cls: "c6", meta: "newest first"});
}

function notebookPanel(name, d){
  const nb = d.notebook || {};
  const files = nb.files || [];
  const list = files.length
    ? files.map(f => `<button data-note="${esc(f.path)}" class="${local.openPath === f.path ? "on" : ""}">` +
        `${esc(f.path)} <span class="dim2">${num(f.bytes)}b</span></button>`).join("")
    : empty("the notebook is empty");
  let reader;
  if (!local.openPath) reader = empty("click a file to read it");
  else if (local.noteBusy) reader = note("reading " + local.openPath + "…");
  else if (local.noteErr) reader = errbox(local.noteErr);
  else if (local.note) reader =
    `<div class="note">${esc(local.note.path || local.openPath)}</div>` +
    `<div class="scrolly tall" data-scroll="notetext"><pre>${esc(local.note.text == null ? "(empty)" : local.note.text)}</pre></div>`;
  else reader = empty("no note loaded");
  const body =
    `<div class="notegrid"><div>` +
      `<div class="note">${files.length} file(s) — its own notes</div>` +
      `<div class="filelist" data-scroll="ci-files">${list}</div>` +
    `</div><div>${reader}</div></div>`;
  return panel("notebook", body, {cls: "c6", meta: "written by this CI"});
}

function instrumentsPanel(d){
  const rows = (d.instruments || []).map(i => [
    `<span class="mono dim">${num(i.tick)}</span>`,
    `<b>${esc(i.name || "?")}</b>`,
    `<span class="wrap dim2">${esc(typeof i.args === "string" ? i.args : JSON.stringify(i.args))}</span>`,
    `<span class="wrap">${esc(typeof i.result === "string" ? i.result : JSON.stringify(i.result))}</span>`,
  ]);
  return panel(`instrument audit trail · ${(d.instruments || []).length}`,
    table(["tick", "instrument", "args", "result"], rows,
      {scroll: "tall", key: "ciinst", empty: "no instrument calls recorded"}),
    {cls: "c6", meta: "everything it ran, in order"});
}

function submissionsPanel(d){
  const subs = d.submissions || [];
  const cards = subs.map(sb => `<div class="card">
    <div class="crole">${chip("t" + esc(sb.task_id))} ${chip("tick " + esc(sb.tick))}
      ${sb.verified ? chip("verified", "on") : chip("not verified", "off")}
      ${sb.verdict ? chip(esc(sb.verdict)) : ""}
      ${sb.score != null ? chip("score " + esc(sb.score)) : ""}</div>
    <div style="margin-top:3px;color:var(--ink2)">${esc(String(sb.answer || "").slice(0, 400))}</div>
    ${sb.detail ? `<div class="crole dim2">${esc(String(sb.detail).slice(0, 200))}</div>` : ""}
  </div>`).join("");
  return panel(`submissions · ${subs.length}`,
    subs.length ? `<div class="scrolly tall" data-scroll="cisub"><div class="stack">${cards}</div></div>`
                : empty("no submissions yet"),
    {cls: "c6", meta: "with verdicts"});
}

function ledgerPanel(d){
  const rows = (d.ledger || []).map(l => [
    `<span class="mono dim">${num(l.tick)}</span>`,
    `<span class="mono ${l.delta > 0 ? "ok" : "badc"}">${l.delta > 0 ? "+" : ""}${num(l.delta)}</span>`,
    `<span class="wrap">${esc(l.reason || "")}</span>`,
    `<span class="mono">${num(l.balance)}</span>`,
  ]);
  return panel("ledger", table(["tick", "delta", "reason", "balance"], rows,
    {scroll: "short", key: "ciled", empty: "no entries"}), {cls: "c4"});
}

function usagePanel(d){
  const rows = (d.usage || []).map(u => [
    `<span class="mono dim">${num(u.tick)}</span>`,
    esc(timeOf(u.ts)),
    esc(u.model || "—"),
    `<span class="tier-${esc(u.tier)}">${esc(u.tier || "—")}</span>`,
    esc(msOf(u.ms)),
    `<span class="mono">${num(u.tokens)}</span>`,
    `<span class="mono dim2">${num(u.prompt_tokens)}/${num(u.completion_tokens)}</span>`,
    u.ok === false ? chip("fail", "off") : chip("ok", "on"),
  ]);
  return panel("usage history", table(["tick", "when", "model", "tier", "ms", "tokens", "p/c", ""], rows,
    {scroll: "short", key: "ciusage", empty: "no model calls yet"}), {cls: "c4"});
}

function eventsPanel(d){
  const rows = (d.events || []).map(e => [
    `<span class="mono dim">${num(e.tick)}</span>`,
    chip(esc(e.kind || "?")),
    `<span class="wrap">${esc(e.text || "")}</span>`,
  ]);
  return panel("events", table(["tick", "kind", "text"], rows,
    {scroll: "short", key: "ciev", empty: "no events with this CI as subject"}), {cls: "c4"});
}

function lineagePanel(d){
  const lin = d.lineage || {};
  const p = lin.parent;
  const kids = lin.children || [];
  const body =
    `<div class="note">parent</div>` +
    (p ? `<div class="card"><div class="cname">${hyper("#/ci/" + encodeURIComponent(p.name), p.name)}</div>` +
         `<div class="crole">${chip(esc(p.tier || "?"))} ${chip("id " + esc(p.id))}</div></div>`
       : empty("none — a founder")) +
    `<div class="note" style="margin-top:7px">children · ${kids.length}</div>` +
    (kids.length ? `<div class="stack">${kids.map(k => `<div class="card">` +
        `<div class="cname">${hyper("#/ci/" + encodeURIComponent(k.name), k.name)}</div>` +
        `<div class="crole">${chip(esc(k.tier || "?"))} ${chip("gen " + esc(k.generation))} ${chip("id " + esc(k.id))}</div>` +
      `</div>`).join("")}</div>` : empty("no children"));
  return panel("lineage", body, {cls: "c4"});
}

function threadPanel(name, d){
  const th = (d.thread || []).slice().reverse(); /* oldest first */
  const turns = th.map(x => `<div class="turn me"><div class="who"><span class="nm">you</span>` +
      `<span class="dim2">${esc(clockOf(x.ts))}</span></div>` +
      `<div class="body">${esc(x.question || "")}</div></div>` +
    `<div class="turn"><div class="who"><span class="nm">${esc(d.agent && d.agent.name || name)}</span>` +
      `${chip(esc(x.model || "?"))}${chip(esc(msOf(x.ms)))}${chip(num(x.tokens) + "t")}</div>` +
      `<div class="body">${esc(x.reply || "")}</div></div>`).join("");
  const body = th.length
    ? `<div class="scrolly tall" data-scroll="cithread"><div class="transcript">${turns}</div></div>`
    : empty("no conversation with me yet");
  return panel(`thread with me · ${th.length}`,
    body + `<div class="actions">${hyper("#/intercom/" + encodeURIComponent(name), "continue this conversation →", "chip")}</div>`,
    {cls: "c8", meta: "saved exchanges"});
}

/* ---------------------------------------------------------------- actions */

function onClick(ev){
  const jump=ev.target.closest("[data-mind-jump]");
  if(jump){
    const peer=jump.getAttribute("data-mind-jump");
    if(window.__w3d&&document.querySelector(".w3d-wrap")) window.__w3d.open("mind",[peer]);
    else location.hash="#/ci/"+encodeURIComponent(peer);
    return;
  }
  const cognitive=ev.target.closest("[data-cog-node]");
  if(cognitive){local.selectedNode=cognitive.getAttribute("data-cog-node");render(ctxRef);return;}
  const btn = ev.target.closest("[data-note]");
  if (btn){
    openNote(btn.getAttribute("data-note"));
    return;
  }
  const act = ev.target.closest("[data-act]");
  if (act && act.getAttribute("data-act") === "refresh"){
    const name = local.name;
    if (name) loadCI(name).then(() => rerenderView());
  }
}
function onKey(ev){
  if((ev.key==="Enter"||ev.key===" ")&&ev.target.closest("[data-cog-node]")){
    ev.preventDefault();local.selectedNode=ev.target.closest("[data-cog-node]").getAttribute("data-cog-node");render(ctxRef);
  }
}
function rerenderView(){
  const ctx = ctxRef;
  if (ctx && ctx.route.params[0] && String(ctx.route.params[0]).toLowerCase() === String(local.name).toLowerCase()){
    render(ctx);
  }
}
async function openNote(path){
  local.openPath = path; local.note = null; local.noteErr = null; local.noteBusy = true;
  rerenderView();
  const r = await getJSON("/api/ci/" + encodeURIComponent(local.name) + "/note?path=" + encodeURIComponent(path),
    {timeout: READ_TIMEOUT_MS});
  if (local.openPath !== path) return;   /* user moved on */
  local.noteBusy = false;
  if (r.ok && r.data && !r.data.error) local.note = r.data;
  else local.noteErr = (r.data && r.data.error) || r.error || "no such note";
  rerenderView();
}
