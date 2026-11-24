import { esc, getJSON, postJSON, paint, panel, note, chip, empty } from "../app.js";

let root = null;
let data = null;
let error = "";
let message = "";
let busy = false;

async function load(){
  const result = await getJSON("/api/world-builder", {timeout: 15000});
  if(result.ok){ data = result.data; error = ""; }
  else error = result.error || "world builder unavailable";
  render();
}

function render(){
  if(!root)return;
  if(error){ paint(root, panel("Vinod Chanda · world asset builder", `<div class="errbox">${esc(error)}</div>`, {cls:"c12 bad"})); return; }
  if(!data){ paint(root, panel("Vinod Chanda · world asset builder", note("loading builder record…"), {cls:"c12"})); return; }
  const assets = data.assets || [];
  const cards = assets.map(a => `<article class="card" style="margin:7px 0;padding:10px;border-left:3px solid ${esc(a.color)}">
    <b>${esc(a.name)}</b> ${chip(esc(a.kind),"solid")}<div class="crole">${esc(a.description)}</div>
    <div class="note">owner ${esc(a.owner)} · ${esc(a.owner_profile)} · ${esc(a.model)} · OpenCode Go cost ${Number(a.cost||0).toFixed(4)}</div>
    <div class="note">site (${Number(a.x).toFixed(1)}, ${Number(a.z).toFixed(1)}) · ${Number(a.width)} × ${Number(a.depth)} × ${Number(a.height)}</div>
  </article>`).join("");
  const body = `<div class="note">Owner: <b>${esc(data.owner)}</b> · Hermes profile <b>${esc(data.profile)}</b> · model <b>${esc(data.model)}</b></div>
    <div class="note">Autobuilder ${data.autobuilder_started ? "running" : "starting"} · interval ${Math.round((data.interval_seconds||900)/60)} min · ${assets.length} saved asset(s)</div>
    <form id="vinod-build-form" style="display:grid;gap:8px;margin:12px 0">
      <label for="vinod-build-brief">Ask Vinod to add something to the living world</label>
      <textarea id="vinod-build-brief" maxlength="500" rows="3" required placeholder="e.g. Add a small electric car for residents commuting between the Foundry and the Agora" style="width:100%;box-sizing:border-box"></textarea>
      <button type="submit" ${busy?"disabled":""}>${busy?"Vinod is building…":"Build with Vinod"}</button>
      ${message?`<div class="note">${esc(message)}</div>`:""}
    </form>
    <div class="note">Every creation is validated, placed by the server, persisted with owner/model/cost, then rendered in Pantheon. Model billing must report OpenCode Go and zero cost.</div>
    <h3>World additions</h3>${cards || empty("Vinod has not added any assets yet.")}`;
  paint(root, panel("Vinod Chanda · world asset builder", body, {cls:"c12", meta:"asset owner · OpenCode Go"}));
}

async function submit(event){
  if(event.target.id!=="vinod-build-form")return;
  event.preventDefault();
  const input=root.querySelector("#vinod-build-brief");
  const brief=(input&&input.value||"").trim();
  if(!brief)return;
  busy=true;message="Waiting for the free OpenCode Go model…";render();
  const result=await postJSON("/api/world-builder/build",{brief},{timeout:90000});
  busy=false;
  if(result.ok){
    const asset=result.data.asset||{};
    message=`Added ${asset.name||"asset"} (${asset.kind||"object"}) by ${asset.owner||data.owner}; model ${result.data.model}; cost ${Number(result.data.cost||0).toFixed(4)}.`;
    await getJSON("/api/pantheon",{timeout:30000});
    await load();
  }else{
    message="Build failed: "+(result.error||"model or validation error");
    render();
  }
}

export function mount(ctx){
  root=ctx.root;data=null;error="";message="";busy=false;
  root.addEventListener("submit",submit);
  render();load();
}
export function update(){ load(); }
export function unmount(){ if(root)root.removeEventListener("submit",submit);root=null;data=null; }
