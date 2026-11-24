/* RESEARCH — what the residents want to find out or build, and the Creator's decision on it.
 * GET  /api/research                 proposals (pending, running, done, rejected, failed)
 * POST /api/research/<id>/approve    hand it to Quorum (one engagement at a time)
 * POST /api/research/<id>/reject     decline; the resident is told and remembers why
 */
import { esc, getJSON, postJSON, paint, panel, note, chip, empty, errbox, agoOf, hyper } from "../app.js";

let root = null, data = null, error = "", message = "", busy = 0, timer = 0;

async function load(){
  const r = await getJSON("/api/research", {timeout: 15000});
  if (r.ok){ data = r.data; error = ""; } else error = r.error || "research proposals unavailable";
  render();
}

const STATUS_CLS = {pending: "warn", running: "on", done: "on", rejected: "off", failed: "bad"};

function card(p){
  const actions = p.status === "pending"
    ? `<div class="actions" style="margin-top:8px">
         <button data-approve="${p.id}" ${busy ? "disabled" : ""}>Approve · run in Quorum</button>
         <input data-reason="${p.id}" placeholder="reason (optional)" maxlength="300" style="flex:1;min-width:160px">
         <button class="small" data-reject="${p.id}" ${busy ? "disabled" : ""}>Decline</button>
       </div>` : "";
  return `<article class="card" style="margin:8px 0;padding:11px">
    <div class="crole">${chip(esc(p.kind))}${chip(esc(p.status), STATUS_CLS[p.status] || "")}
      ${hyper("#/ci/" + encodeURIComponent(p.name), esc(p.name), "chip")}
      <span class="hint">${esc(agoOf(p.ts))}</span>
      ${p.engagement_id ? chip("Quorum engagement #" + esc(p.engagement_id)) : ""}</div>
    <div style="margin-top:6px"><b>${esc(p.topic)}</b></div>
    <div class="hint" style="margin-top:3px">why · ${esc(p.why)}</div>
    ${p.verdict ? `<div style="margin-top:6px">verdict · <b>${esc(p.verdict)}</b></div>` : ""}
    ${p.summary ? `<div class="hint" style="margin-top:4px">${esc(p.summary.slice(0, 420))}…</div>` : ""}
    ${p.paper_path ? `<div class="hint">paper · ${esc(p.paper_path)}</div>` : ""}
    ${p.error ? `<div class="badc">${esc(p.error)}</div>` : ""}
    ${actions}
  </article>`;
}

function render(){
  if (!root) return;
  if (error){ paint(root, panel("research", errbox(error), {cls: "c12 bad"})); return; }
  if (!data){ paint(root, panel("research", note("loading proposals…"), {cls: "c12"})); return; }
  const all = data.proposals || [];
  const pending = all.filter(p => p.status === "pending"), rest = all.filter(p => p.status !== "pending");
  paint(root,
    panel(`awaiting your decision · ${pending.length}`,
      (message ? note(message) : "") +
      note("Residents propose questions their work needs evidence for, or software the town needs. Approving one starts a Quorum engagement (real search, computation, verification, adjudication; builds get Quorum's engineering handoff). Quorum runs one engagement at a time and spends its configured model.") +
      (pending.length ? pending.map(card).join("") : empty("no proposals waiting")),
      {cls: "c12", meta: "Quorum · " + esc(data.quorum_url)}) +
    panel(`history · ${rest.length}`, rest.length ? rest.map(card).join("") : empty("nothing decided yet"), {cls: "c12"}));
}

async function onClick(ev){
  const approve = ev.target.closest("[data-approve]"), reject = ev.target.closest("[data-reject]");
  if (!approve && !reject) return;
  const id = (approve || reject).dataset.approve || (approve || reject).dataset.reject;
  busy++; render();
  const r = approve
    ? await postJSON(`/api/research/${id}/approve`, {}, {timeout: 30000})
    : await postJSON(`/api/research/${id}/reject`, {reason: (root.querySelector(`[data-reason="${id}"]`) || {}).value || ""}, {timeout: 15000});
  busy--;
  message = r.ok ? (approve ? `#${id} handed to Quorum.` : `#${id} declined.`) : (r.error || "request failed");
  await load();
}

export function mount(ctx){
  root = ctx.root; root.addEventListener("click", onClick);
  load(); clearInterval(timer); timer = setInterval(load, 15000);
}
export function update(){}
export function unmount(ctx){ clearInterval(timer); if (root) root.removeEventListener("click", onClick); root = null; }
