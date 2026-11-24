/* TALK (intercom) — pick a CI, send it a message, read its answer in its own voice.
 * POST /api/ci/<name>/ask  (ONE live model call — costs tokens)
 * GET  /api/ci/<name>      (its saved thread with MIST)
 * Not polled: a glance at the clock must never wipe a half-typed message.
 */
import {
  state, paint, esc, num, msOf, secsOf, clockOf, chip, panel,
  empty, note, errbox, hyper, loadCI, loadColony, ciSlot, colonyAgents, colonyData,
  postJSON, beginSpend, endSpend, TALK_TIMEOUT_MS,
} from "../app.js";
import { sigil } from "../being.js";

let st = {name: null, draft: "", pending: false, err: null, local: [], startedAt: 0, sent: 0, tok: 0,
  recording: false, voiceBusy: false, recorder: null, micStream: null, recordTimer: null, audioURLs: []};
let periodic = null;
let ctxRef = null;

export function mount(ctx){
  ctxRef = ctx;
  const wanted = ctx.route.params[0];
  if (wanted && String(wanted).toLowerCase() !== String(st.name || "").toLowerCase()){
    st.name = wanted; st.local = []; st.err = null;
  }
  if (!st.name){
    const ag = colonyAgents();
    if (ag.length) st.name = ag[0].name;
  }
  ctx.root.addEventListener("click", onClick);
  ctx.root.addEventListener("input", onInput);
  ctx.root.addEventListener("keydown", onKey);
  if (!state.colony) loadColony().then(() => { if (ctxRef === ctx) render(ctx); });
  if (st.name && !ciSlot(st.name)) loadCI(st.name).then(() => { if (ctxRef === ctx) render(ctx); });
  render(ctx);
}
export function unmount(ctx){
  if (ctx && ctx.root){
    ctx.root.removeEventListener("click", onClick);
    ctx.root.removeEventListener("input", onInput);
    ctx.root.removeEventListener("keydown", onKey);
  }
  stopTicker();
  cleanupVoice();
  ctxRef = null;
}

function render(ctx){
  paint(ctx.root, pickerPanel() + conversationPanel());
  refreshMetaLine();
}

/* --------------------------------------------------------------- picker */

function pickerPanel(){
  const agents = colonyAgents();
  const c = colonyData();
  let list;
  if (agents.length){
    list = agents.map(a => {
      const on = st.name && a.name.toLowerCase() === String(st.name).toLowerCase();
      return `<button data-ci="${esc(a.name)}" class="ciopt ${on ? "sel" : ""}">` +
        sigil(a, 26) +
        `<span><b>${esc(a.name)}</b> <span class="tier-${esc(a.tier)}">${esc(a.tier)}</span> <span class="dim">${esc(a.domain)}</span></span>` +
        (a.status === "active" ? "" : chip(esc(a.status || "?"), "warnb")) +
        (a.doing ? chip("working", "infob") : "") +
        `</button>`;
    }).join("");
  } else {
    list = (state.colonyErr ? errbox(state.colonyErr) : empty("the colony roster is not readable yet")) +
      note("you can still type a name below.");
  }
  const tiers = c && c.models ? c.models : {};
  const body =
    `<div class="note" style="margin-bottom:5px">choose a CI to speak with</div>` +
    `<div class="picker" data-scroll="talk-picker">${list}</div>` +
    `<div style="margin-top:7px"><div class="note">or name one directly</div>` +
    `<div class="rowline"><input type="text" id="talk-name" placeholder="CI name" style="flex:1">` +
    `<button class="small" data-act="setname">open</button></div></div>` +
    (Object.keys(tiers).length
      ? `<div class="note" style="margin-top:7px">tier models: ` +
        ["reflex", "worker", "specialist", "architect"].filter(k => tiers[k])
          .map(k => `${esc(k)}=${esc(tiers[k])}`).join(" · ") + `</div>`
      : "");
  return panel("talk · pick a CI", body, {cls: "c3", meta: `${colonyAgents().length} CIs`});
}

/* ---------------------------------------------------------- conversation */

function turns(){
  const slot = ciSlot(st.name || "");
  const server = (slot && slot.data && Array.isArray(slot.data.thread)) ? slot.data.thread.slice() : [];
  const all = st.local.concat(server);
  const seen = {}, out = [];
  all.forEach(x => {
    const id = (x && x.id != null) ? "id:" + x.id : "x:" + JSON.stringify([x && x.ts, x && x.question]);
    if (!seen[id]){ seen[id] = 1; out.push(x); }
  });
  out.sort((a, b) => (Number(a && a.ts) || 0) - (Number(b && b.ts) || 0));
  return out;
}

function threadHTML(){
  const t = turns();
  if (!t.length && !st.pending && st.name){
    return `<div class="chatlog">${note(st.name + " has not spoken with me yet. Say something.")}</div>`;
  }
  const html = t.map(x => turnPair(x)).join("");
  const pend = st.pending
    ? `<div class="msg"><div class="msgbody"><div class="thinking"><span class="dots"><i></i><i></i><i></i></span>` +
      `${esc(st.name)} is thinking… <span class="mono" id="talk-elapsed" style="color:var(--dim)">0s</span></div></div></div>`
    : "";
  return `<div class="chatlog">${html}${pend}</div>`;
}

function turnPair(x){
  const name = st.name || "";
  const who = x.ci ? x.ci : name;
  const agent = (ciSlot(st.name) && ciSlot(st.name).data && ciSlot(st.name).data.agent) || {};
  return `<div class="msg me"><div class="msgbody"><div class="msgwho">you · ${esc(clockOf(x.ts))}</div>` +
      `<div class="msgtext">${esc(x.question || "")}</div></div></div>` +
    `<div class="msg">${sigil(agent, 40)}` +
      `<div class="msgbody"><div class="msgwho">${esc(who)}</div>` +
      `<div class="msgtext">${esc(x.reply || "(empty reply)")}</div>` +
      (x.audioUrl ? `<audio controls autoplay src="${esc(x.audioUrl)}" aria-label="${esc(who)} speaking"></audio>` : "") +
      `<div class="msgmeta">${esc(x.model || "?")} · ${esc(msOf(x.ms))} · ${num(x.tokens)} tok${x.voice_label ? " · voice " + esc(x.voice_label) : ""}</div></div></div>`;
}

function conversationPanel(){
  if (!st.name){
    return panel("the conversation", empty("pick a CI on the left") +
      note("talking to a CI runs one live model call; the CI answers as itself, with its own memory, notebook and current task as context."),
      {cls: "c9"});
  }
  const slot = ciSlot(st.name);
  const d = slot && slot.data;
  const a = d && d.agent ? d.agent : {};
  const c = colonyData();
  const tiers = c && c.models ? c.models : {};
  const snap = stats();
  const meta =
    `<span class="tier-${esc(a.tier)}">${esc(a.tier || "tier ?")}</span>` +
    (a.domain ? chip(esc(a.domain)) : "") +
    chip("model " + esc(tiers[a.tier] || "tier default")) +
    (a.status ? (a.status === "active" ? chip("active", "on") : chip(esc(a.status), "warnb")) : "") +
    (slot && slot.err ? chip("stale/err", "off") : "");
  const body =
    (slot && slot.err ? errbox("cannot re-read this CI: " + slot.err + " — showing what we have.") : "") +
    `<div class="rowline" style="margin-bottom:8px;align-items:center;gap:14px">` +
      sigil(a, 52) +
      `<div style="flex:1;min-width:200px">` +
        `<div style="font-size:17px;font-weight:700">${esc(st.name)}</div>` +
        `<div class="mindmeta">${esc(a.tier || "tier ?")} · ${esc(a.domain || "—")} · fitness ${a.fitness != null ? Number(a.fitness).toFixed(2) : "—"} · ${num(Math.round(a.credits || 0))} credits</div>` +
      `</div>` +
      (a.doing ? chip("on task t" + esc(a.doing.task_id) + " · " + esc(String(a.doing.question || "").slice(0, 40)), "infob") : chip("idle")) +
      hyper("#/ci/" + encodeURIComponent(st.name), "open its brain →", "hint") +
    `</div>` +
    `<div class="scrolly tall" data-scroll="talk-thread">${threadHTML()}</div>` +
    `<div class="cost">Each message is <b>one live model call</b> (the CI's tier model) and spends tokens. ` +
      `This session: <b>${snap.calls}</b> call(s), <b>${num(snap.tokens)}</b> tokens.</div>` +
    `<textarea id="talk-input" rows="3" ${st.pending ? "disabled" : ""} ` +
      `placeholder="${st.pending ? "waiting for the reply…" : "say something to " + esc(st.name) + "  (⌘/Ctrl+Enter to send)"}">${esc(st.draft)}</textarea>` +
    (st.err ? errbox(st.err) : "") +
    `<div class="actions">` +
      `<button class="primary" id="talk-send" data-act="send" ${st.pending || st.recording ? "disabled" : ""}>` +
        (st.pending ? "sending…" : "send · 1 live call") + `</button>` +
      `<button class="small voice-button" data-act="voice" ${st.pending || st.voiceBusy ? "disabled" : ""}>` +
        (st.recording ? "stop & send voice" : st.voiceBusy ? "voice turn in progress…" : "🎙 talk by voice") + `</button>` +
      `<button class="small" data-act="clear" ${st.pending || st.recording ? "disabled" : ""}>clear box</button>` +
      `<span class="hint" id="talk-elapsed-wrap">${st.recording ? "recording — click stop & send when done" : ""}</span>` +
    `</div>` +
    `<div class="note voice-note">Mic audio is transcribed locally; only the transcript goes to the CI. Replies are spoken locally by macOS.</div>`;
  return panel("the conversation", body, {cls: "c9", meta});
}

function stats(){
  const t = turns();
  let tok = 0;
  t.forEach(x => { tok += Number(x && x.tokens) || 0; });
  return {calls: t.length, tokens: tok};
}

function refreshMetaLine(){
  const el = document.getElementById("talk-elapsed-wrap");
  if (!el) return;
  const snap = stats();
  el.textContent = st.recording ? "recording · click stop & send when finished" :
    (st.pending ? "a live call is in flight — polling is paused" :
      `${snap.calls} exchange(s) on record · ${num(snap.tokens)} tokens shown`);
}

/* ---------------------------------------------------------------- actions */

function onClick(ev){
  const ciBtn = ev.target.closest("[data-ci]");
  if (ciBtn){
    const name = ciBtn.getAttribute("data-ci");
    if (name && name.toLowerCase() !== String(st.name || "").toLowerCase()){
      st.name = name; st.local = []; st.err = null;
      loadCI(name).then(() => { if (ctxRef) render(ctxRef); });
      render(ctxRef);
    }
    return;
  }
  const act = ev.target.closest("[data-act]");
  if (!act) return;
  const a = act.getAttribute("data-act");
  if (a === "send") send();
  else if (a === "voice"){ if (st.recording) finishVoiceRecording(); else startVoiceRecording(); }
  else if (a === "clear"){ st.draft = ""; render(ctxRef); }
  else if (a === "setname"){
    const inp = document.getElementById("talk-name");
    const name = inp && inp.value.trim();
    if (name){ st.name = name; st.local = []; st.err = null; loadCI(name); render(ctxRef); }
  }
}
function onInput(ev){
  if (ev.target && ev.target.id === "talk-input") st.draft = ev.target.value;
}
function onKey(ev){
  if (ev.target && ev.target.id === "talk-input" && ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)){
    ev.preventDefault();
    send();
  }
}

async function startVoiceRecording(){
  if (!st.name || st.pending || st.recording || st.voiceBusy) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder){
    st.err = "This browser cannot record microphone audio. Use a current Safari or Chromium browser over localhost.";
    render(ctxRef); return;
  }
  st.err = null; st.voiceBusy = true; render(ctxRef);
  try{
    const stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1, echoCancellation:true, noiseSuppression:true}});
    if (!ctxRef){ stream.getTracks().forEach(t => t.stop()); return; }
    st.micStream = stream;
    const chunks = [];
    const recorder = new MediaRecorder(stream);
    st.recorder = recorder; st.recording = true; st.voiceBusy = false;
    recorder.ondataavailable = ev => { if (ev.data && ev.data.size) chunks.push(ev.data); };
    recorder.onerror = () => { st.err = "Microphone recording failed."; finishVoiceRecording(); };
    recorder.onstop = () => {
      st.recording = false; st.voiceBusy = true; st.recorder = null;
      if (st.recordTimer){ clearTimeout(st.recordTimer); st.recordTimer = null; }
      if (st.micStream){ st.micStream.getTracks().forEach(t => t.stop()); st.micStream = null; }
      if(st.err){ st.voiceBusy=false; render(ctxRef); return; }
      render(ctxRef);
      const blob = new Blob(chunks, {type: recorder.mimeType || "audio/webm"});
      processVoiceBlob(blob);
    };
    recorder.start(250);
    st.recordTimer = setTimeout(finishVoiceRecording, 45000);
    render(ctxRef);
  } catch(e){
    st.recording = false; st.voiceBusy = false;
    if (st.micStream){ st.micStream.getTracks().forEach(t => t.stop()); st.micStream = null; }
    st.err = e && e.name === "NotAllowedError"
      ? "Microphone permission was denied. Allow this local MIST page to use the microphone, then try again."
      : (e && e.message) || "Could not open the microphone.";
    render(ctxRef);
  }
}

function finishVoiceRecording(){
  if (!st.recorder || st.recorder.state === "inactive") return;
  if (st.recordTimer){ clearTimeout(st.recordTimer); st.recordTimer = null; }
  st.recording = false; st.voiceBusy = true; render(ctxRef);
  try{ st.recorder.stop(); }catch(e){ st.voiceBusy = false; st.err = "Could not stop the microphone recording."; render(ctxRef); }
}

async function processVoiceBlob(blob){
  try{
    const wav = await blobToWav(blob);
    await sendVoiceAudio(wav);
  }catch(e){
    st.pending = false; st.voiceBusy = false;
    st.err = (e && e.message) || "Could not prepare the recording.";
    stopTicker(); render(ctxRef);
  }
}

async function blobToWav(blob){
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) throw new Error("This browser does not support local audio decoding.");
  const audioContext = new AudioCtx();
  let decoded;
  try{ decoded = await audioContext.decodeAudioData(await blob.arrayBuffer()); }
  finally{ await audioContext.close(); }
  const targetRate = 16000;
  const outCount = Math.floor(decoded.length * targetRate / decoded.sampleRate);
  if (!outCount) throw new Error("The recording was empty.");
  const mono = new Float32Array(decoded.length);
  for(let c=0;c<decoded.numberOfChannels;c++){
    const src = decoded.getChannelData(c);
    for(let i=0;i<src.length;i++) mono[i] += src[i] / decoded.numberOfChannels;
  }
  const pcm = new ArrayBuffer(44 + outCount * 2), view = new DataView(pcm);
  const put = (offset, text) => { for(let i=0;i<text.length;i++) view.setUint8(offset+i,text.charCodeAt(i)); };
  put(0,"RIFF"); view.setUint32(4,36+outCount*2,true); put(8,"WAVE"); put(12,"fmt ");
  view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true);
  view.setUint32(24,targetRate,true); view.setUint32(28,targetRate*2,true);
  view.setUint16(32,2,true); view.setUint16(34,16,true); put(36,"data"); view.setUint32(40,outCount*2,true);
  const step = decoded.sampleRate / targetRate;
  for(let i=0;i<outCount;i++){
    const at=i*step, lo=Math.floor(at), hi=Math.min(lo+1,mono.length-1), frac=at-lo;
    const f=Math.max(-1,Math.min(1,mono[lo]*(1-frac)+mono[hi]*frac));
    view.setInt16(44+i*2, f<0 ? f*32768 : f*32767, true);
  }
  return new Blob([pcm],{type:"audio/wav"});
}

async function sendVoiceAudio(wav){
  const name=st.name;
  st.pending=true; st.voiceBusy=true; st.startedAt=Date.now(); st.err=null;
  render(ctxRef); startTicker(); beginSpend("voice conversation with "+name);
  const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),TALK_TIMEOUT_MS);
  try{
    const response=await fetch("/api/voice/"+encodeURIComponent(name)+"/turn",{
      method:"POST",headers:{"Content-Type":"audio/wav"},body:wav,signal:controller.signal
    });
    const data=await response.json();
    if(!response.ok) throw new Error((data && data.error) || "The voice turn failed.");
    const audio64=data.audio_base64; delete data.audio_base64;
    if(audio64){
      const raw=atob(audio64), bytes=new Uint8Array(raw.length);
      for(let i=0;i<raw.length;i++) bytes[i]=raw.charCodeAt(i);
      data.audioUrl=URL.createObjectURL(new Blob([bytes],{type:data.audio_mime||"audio/wav"}));
      st.audioURLs.push(data.audioUrl);
    }
    st.local.push(data); st.sent++; st.tok+=Number(data.tokens)||0;
    if(data.voice_error) st.err="CI replied, but local speech synthesis failed: "+data.voice_error;
    loadCI(name).then(()=>{if(ctxRef)render(ctxRef);});
  }catch(e){
    st.err=(e && e.name==="AbortError") ? "Voice turn timed out; try a shorter recording." :
      ((e && e.message) || "The voice turn failed.");
  }finally{
    clearTimeout(timeout); endSpend(); stopTicker(); st.pending=false; st.voiceBusy=false;
    if(ctxRef) render(ctxRef);
  }
}

function cleanupVoice(){
  if(st.recordTimer){clearTimeout(st.recordTimer);st.recordTimer=null;}
  if(st.recorder){
    st.recorder.onstop=null;
    try{if(st.recorder.state!=="inactive")st.recorder.stop();}catch(e){}
    st.recorder=null;
  }
  if(st.micStream){st.micStream.getTracks().forEach(t=>t.stop());st.micStream=null;}
  st.recording=false;st.voiceBusy=false;
  st.audioURLs.forEach(url=>URL.revokeObjectURL(url));st.audioURLs=[];
  st.local.forEach(x=>{if(x.audioUrl)delete x.audioUrl;});
}

async function send(){
  const name = st.name;
  const box = document.getElementById("talk-input");
  const msg = (box ? box.value : st.draft).trim();
  if (!name || !msg || st.pending) return;
  st.draft = ""; st.err = null; st.pending = true; st.startedAt = Date.now();
  if (box) box.value = "";
  render(ctxRef);
  startTicker();
  beginSpend("talking to " + name);
  const r = await postJSON("/api/ci/" + encodeURIComponent(name) + "/ask",
                           {message: msg}, {timeout: TALK_TIMEOUT_MS});
  endSpend();
  stopTicker();
  st.pending = false;
  if (r.ok && r.data){
    st.local.push(r.data);
    st.sent++;
    st.tok += Number(r.data.tokens) || 0;
    loadCI(name).then(() => { if (ctxRef) render(ctxRef); });
  } else {
    st.err = (r.data && r.data.error) || r.error || "the call failed";
    st.draft = msg;            /* never lose the message */
  }
  render(ctxRef);
}

function startTicker(){
  stopTicker();
  const t0 = Date.now();
  periodic = setInterval(() => {
    const el = document.getElementById("talk-elapsed");
    if (el) el.textContent = secsOf((Date.now() - t0) / 1000);
  }, 500);
}
function stopTicker(){ if (periodic){ clearInterval(periodic); periodic = null; } }
