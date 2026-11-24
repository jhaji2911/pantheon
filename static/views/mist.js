/* MIST — the god's panel: the operating commands, in the web.
 *
 * The one deliberate write path in an otherwise read-only console. Every action
 * is an explicit POST to /api/mist/act, confirmed by the button the operator
 * presses. GET /api/mist supplies the panel: pending petitions, the standing
 * directive, reach, reviews awaiting verdict, and the roster to act on.
 */
import {
  state, paint, esc, dsh, has, num, f2, chip, kv, panel, table, empty, note, errbox,
  getJSON, postJSON, beginSpend, endSpend, loadColony, colonyData,
} from "../app.js";

let last = null;       // /api/mist menu
let result = null;     // last /api/mist/act outcome
let mctx = null;       // the view context, for the delegated click handler

export function mount(ctx){
  mctx = ctx;
  bind(ctx.root);
  load();
  render(ctx);
}
export function update(ctx){ render(ctx); }
export function unmount(ctx){ ctx.root.__html = null; }

async function load(){
  const r = await getJSON("/api/mist", {timeout: 30000});
  if (r.ok && !(r.data && r.data.error && !r.data.roster)) last = r.data;
  else last = {error: (r.data && r.data.error) || r.error || "unreadable"};
}

async function act(action, fields){
  beginSpend("mist: " + action);
  result = null;
  try {
    const r = await postJSON("/api/mist/act",
      Object.assign({action}, fields || {}), {timeout: 300000});
    if (r.ok && r.data && r.data.menu){ last = r.data.menu; result = r.data; }
    else result = {error: (r.data && r.data.error) || r.error || ("HTTP " + r.status), raw: r.data};
  } finally {
    endSpend();
  }
  loadColony();
  render(mctx);
}

function bind(root){
  root.addEventListener("click", ev => {
    const b = ev.target.closest("[data-act]");
    if (!b) return;
    ev.preventDefault();
    const action = b.getAttribute("data-act");
    const id = b.getAttribute("data-id");
    const val = sel => { const el = document.getElementById(sel); return el ? el.value.trim() : ""; };
    const fields = {};
    switch (action){
      case "petition-approve":
      case "petition-reject": fields.id = id; break;
      case "judge-accept":
      case "judge-reject": fields.task = id; break;
      case "note": fields.text = val("mist-note"); break;
      case "note-clear": break;
      case "grant":
        fields.agent = val("mist-grant-agent");
        fields.credits = val("mist-grant-credits");
        fields.reason = val("mist-grant-reason"); break;
      case "spawn": fields.agent = val("mist-spawn-agent"); break;
      case "reach-on": case "reach-off": case "reach-status": break;
      case "dispatch": fields.brief = val("mist-dispatch-brief"); break;
      default: return;
    }
    act(action, fields);
  });
}

// ------------------------------------------------------------------ render
function render(ctx){
  if (!last){
    paint(ctx.root, panel("the god", note("reading the colony…"), {cls: "c12"}));
    return;
  }
  if (last.error && !last.roster){
    paint(ctx.root, panel("the god", errbox(last.error), {cls: "c12 bad"}));
    return;
  }
  const parts = [];
  parts.push(resultPanel());
  parts.push(directivePanel());
  parts.push(petitionsPanel());
  parts.push(reviewsPanel());
  parts.push(reachPanel());
  parts.push(grantPanel());
  parts.push(spawnPanel());
  parts.push(dispatchPanel());
  paint(ctx.root, parts.filter(Boolean).join(""));
}

function resultPanel(){
  if (!result) return "";
  const ok = result.error == null;
  const body =
    (result.error ? errbox(result.error) : "") +
    (has(result.stdout) ? `<div class="scrolly short" data-scroll="mist-out"><pre>${esc(result.stdout)}</pre></div>` : "") +
    (result.stderr ? `<div class="note">stderr: ${esc(String(result.stderr).slice(0, 400))}</div>` : "");
  return panel("last act", body, {cls: "c12 " + (ok ? "good" : "bad"),
    meta: ok ? chip("done", "on") : chip("failed", "off")});
}

function directivePanel(){
  const d = last.directive;
  return panel("standing directive",
    (d ? `<div class="note" style="margin-bottom:6px">in force:</div><pre>${esc(d)}</pre>` : note("no directive set")) +
    `<div class="rowline" style="margin-top:8px">` +
    `<input id="mist-note" type="text" placeholder="new directive…">` +
    `<button data-act="note" class="primary">set</button>` +
    `<button data-act="note-clear">clear</button></div>`,
    {cls: "c6", meta: "every CI reads this on its next action"});
}

function petitionsPanel(){
  const ps = last.petitions || [];
  const cards = ps.map(p => `<div class="card">
    <div class="crole">#${esc(p.id)} ${chip("tick " + esc(p.tick))} ${chip(esc(p.kind || "?"))}
      ${p.agent_id != null ? chip("CI " + esc(p.agent_id)) : ""}</div>
    <div style="margin-top:4px;color:var(--ink2)">${esc(p.body || "")}</div>
    <div class="rowline" style="margin-top:8px">
      <button data-act="petition-approve" data-id="${esc(p.id)}" class="primary">approve</button>
      <button data-act="petition-reject" data-id="${esc(p.id)}">veto</button>
    </div></div>`).join("");
  return panel(`petitions · ${num(ps.length)} waiting on me`,
    cards ? `<div class="stack">${cards}</div>` : empty("nothing waiting"),
    {cls: "c6", meta: "approve births the CI; veto is final and reasonless"});
}

function reviewsPanel(){
  const rs = last.reviews || [];
  const cards = rs.map(t => `<div class="card">
    <div class="crole">task ${esc(t.id)} ${chip(esc(t.domain || "?"))} d${num(t.difficulty)} reward ${num(t.reward)}
      ${t.claimed_by_name ? chip(esc(t.claimed_by_name)) : ""}</div>
    <div style="margin-top:4px;color:var(--ink2)">${esc(String(t.question || "").slice(0, 200))}</div>
    <div class="rowline" style="margin-top:8px">
      <button data-act="judge-accept" data-id="${esc(t.id)}" class="primary">accept</button>
      <button data-act="judge-reject" data-id="${esc(t.id)}">reject</button>
    </div></div>`).join("");
  return panel(`reviews · ${num(rs.length)} awaiting my verdict`,
    cards ? `<div class="stack">${cards}</div>` : empty("nothing to judge"),
    {cls: "c6", meta: "prose briefs land here; nothing is paid until I rule"});
}

function reachPanel(){
  const r = last.reach;
  return panel("hermes reach",
    kv("status", r == null ? "—" : (r ? chip("GRANTED", "on") : chip("withheld", "off"))) +
    `<div class="note">architects may borrow a Hermes agent when granted. Operator-only — no petition can touch it.</div>` +
    `<div class="rowline" style="margin-top:8px">
      <button data-act="reach-on" class="primary">grant</button>
      <button data-act="reach-off">withdraw</button></div>`,
    {cls: "c4"});
}

function rosterOptions(id, selected){
  const rows = (last.roster || []).map(a =>
    `<option value="${esc(a.name)}"${selected === a.name ? " selected" : ""}>${esc(a.name)} · ${esc(a.tier)} · ${esc(a.domain)} · ${num(Math.round(a.credits))}cr</option>`).join("");
  return `<select id="${id}">${rows}</select>`;
}

function grantPanel(){
  const first = (last.roster && last.roster[0]) ? last.roster[0].name : "";
  return panel("mint credits",
    `<div class="rowline">${rosterOptions("mist-grant-agent", first)}</div>` +
    `<div class="rowline" style="margin-top:6px">
      <input id="mist-grant-credits" type="text" placeholder="credits (e.g. 10)" style="width:9em">
      <input id="mist-grant-reason" type="text" placeholder="why (optional)"></div>` +
    `<div class="rowline" style="margin-top:8px"><button data-act="grant" class="primary">grant</button></div>`,
    {cls: "c4", meta: "the only external source of credits"});
}

function spawnPanel(){
  const first = (last.roster && last.roster[0]) ? last.roster[0].name : "";
  return panel("force a birth",
    `<div class="rowline">${rosterOptions("mist-spawn-agent", first)}</div>` +
    `<div class="rowline" style="margin-top:8px"><button data-act="spawn" class="primary">spawn</button></div>`,
    {cls: "c4", meta: "a new CI, cost paid by the parent"});
}

function dispatchPanel(){
  return panel("hand out a brief",
    `<div class="rowline"><textarea id="mist-dispatch-brief" rows="3"
      placeholder="a named deliverable with a way to verify it was produced…"></textarea></div>` +
    `<div class="rowline" style="margin-top:8px"><button data-act="dispatch" class="primary">dispatch</button></div>` +
    `<div class="note" style="margin-top:6px">spends tokens (one live run). Prose briefs land in reviews.</div>`,
    {cls: "c6"});
}
