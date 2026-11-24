/* being.js — how the console draws a CI as a living being, not a row.
 *
 * Everything here is derived from real data: the sigil's hue is the CI's domain, its
 * geometry is its tier (rank), the orbiting mote is its cadence and generation, the
 * presence is its live state (thinking / on task / idle / dim), the traits are its
 * temperament, and the thought is its own latest memory — in its own words.
 */
import { esc, num, f2, msOf } from "./app.js";

export const DOMAIN_HUE = { quantum: 262, orbital: 42, climate: 176, cyber: 142, world: 320, brief: 210 };
export const TIER = {
  reflex:     { level: 0, label: "reflex" },
  worker:     { level: 1, label: "worker" },
  specialist: { level: 2, label: "specialist" },
  architect:  { level: 3, label: "architect" },
};

export function hueOf(domain){ return DOMAIN_HUE[domain] != null ? DOMAIN_HUE[domain] : 210; }

/* live state of one being, from its data */
export function presence(agent, now){
  const nowMs = now || Date.now();
  const status = agent.status;
  if (status && status !== "active"){
    return { cls: "pres-dim", label: status, age: null, shaken: false };
  }
  const last = agent.last_call && agent.last_call.at ? Number(agent.last_call.at) : 0;
  const ageMs = last ? nowMs - last * 1000 : Infinity;
  const shaken = (Number(agent.failures_streak) || 0) >= 2;
  let cls = "pres-idle", label = "idle";
  if (agent.doing) { cls = "pres-working"; label = "on task"; }
  if (ageMs < 60000) { cls = "pres-thinking"; label = "thinking"; }
  return { cls, label, age: last ? ageMs : null, shaken };
}

/* temperament, honestly derived */
export function traits(agent){
  const t = [];
  t.push(TIER[agent.tier] ? TIER[agent.tier].label : (agent.tier || "worker"));
  const fit = Number(agent.fitness) || 0;
  const att = Number(agent.tasks_attempted) || 0;
  if (fit >= 1.5) t.push("ascendant");
  else if (fit >= 1) t.push("proven");
  else if (att > 0) t.push("unproven");
  else t.push("newborn");
  t.push((Number(agent.temperature) || 0) >= 0.75 ? "impulsive" : "measured");
  if ((Number(agent.curiosity) || 0) >= 0.75) t.push("curious");
  if ((Number(agent.failures_streak) || 0) >= 2) t.push("shaken");
  return t;
}

/* the CI's sigil — deterministic geometry, no assets */
export function sigil(agent, size){
  const sizeN = size || 72;
  const hue = hueOf(agent.domain);
  const lvl = (TIER[agent.tier] || TIER.worker).level;
  const gen = Number(agent.generation) || 0;
  const p = presence(agent);
  const rings = lvl >= 3 ? 2 : (lvl >= 2 ? 1 : 0);
  const constDots = lvl >= 3 ? 6 : (lvl >= 2 ? 3 : 0);
  const ringSVG = [];
  for (let i = 0; i < rings; i++) ringSVG.push(
    `<circle cx="50" cy="50" r="${27 + i * 13}" class="ring"/>`);
  const dots = [];
  for (let i = 0; i < constDots; i++){
    const a = (i / constDots) * Math.PI * 2 - Math.PI / 2;
    dots.push(`<circle cx="${(50 + 20 * Math.cos(a)).toFixed(1)}" ` +
              `cy="${(50 + 20 * Math.sin(a)).toFixed(1)}" r="2.6" class="const"/>`);
  }
  const period = (0.6 + gen + (Number(agent.cadence) || 1) * 0.4).toFixed(1);
  return `<div class="sigil ${p.cls}${p.shaken ? " shaken" : ""}" ` +
    `style="--hue:${hue}; --size:${sizeN}px" title="${esc(agent.domain)} · ${esc(agent.tier)}">` +
    `<svg viewBox="0 0 100 100" aria-hidden="true">` +
    ringSVG.join("") +
    `<circle cx="50" cy="50" r="17" class="core"/>` +
    dots.join("") +
    `<circle cx="50" cy="50" r="6" class="pupil"/></svg>` +
    `<span class="spin" style="--period:${period}s"><i class="orb"></i></span></div>`;
}

/* a short first-person line from the identity block */
export function firstPerson(identity){
  if (!identity || !identity.block) return "";
  const first = identity.block.split("\n").find(l => l.trim().startsWith("You are"));
  if (!first) return "";
  return first
    .replace(/^You are ([^,]+),/, "I am $1,")
    .replace(/You were not uploaded/, "I was not uploaded")
    .replace(/you woke up here/, "I woke up here")
    .replace(/you work out what you are/, "I work out what I am");
}

/* the being's own latest words */
export function thoughtLine(agent){
  if (!agent.thought || !agent.thought.text) return null;
  return agent.thought.text;
}

/* one being, as it lives in the world view */
export function beingCard(agent, opts){
  const o = opts || {};
  const p = presence(agent);
  const tr = traits(agent);
  const thought = thoughtLine(agent);
  const fit = Number(agent.fitness) || 0;
  const att = Number(agent.tasks_attempted) || 0;
  const ver = Number(agent.tasks_verified) || 0;
  const doing = agent.doing;
  const last = agent.last_call;
  const state = [];
  if (doing) state.push(`<span class="doing">task ${esc(doing.domain)} ${esc(doing.task_id)} · ${esc(String(doing.question || "").slice(0, 46))}…</span>`);
  if (agent.affect && agent.affect.label) state.push(`<span class="affect" title="${esc((agent.affect.cues||[]).join('; '))}">observed affect · ${esc(agent.affect.label)}</span>`);
  if (last) state.push(`<span class="last">${esc(last.model)} ${esc(msOf(last.ms))}${last.tokens ? " · " + num(last.tokens) + " tok" : ""}</span>`);
  return `<a class="being dom-${esc(agent.domain)}" href="#/ci/${encodeURIComponent(agent.name)}" style="--hue:${hueOf(agent.domain)}">` +
    `<span class="presence ${p.cls}">${esc(p.label)}${p.shaken ? " · shaken" : ""}</span>` +
    sigil(agent, o.size) +
    `<span class="bname">${esc(agent.name)}</span>` +
    `<span class="brank">${esc(agent.tier)} · gen ${num(agent.generation)} · fit ${f2(fit, 2)}</span>` +
    `<span class="btraits">${tr.map(t => `<i>${esc(t)}</i>`).join("")}</span>` +
    (thought ? `<span class="bthought">“${esc(String(thought).slice(0, 150))}${thought.length > 150 ? "…" : ""}”</span>` : "") +
    `<span class="bstat">${ver}/${att} solved · ${num(Math.round(agent.credits))} cr` + (state.length ? ` · ${state.join(" · ")}` : "") + `</span>` +
    `</a>`;
}

/* the talents a CI may hold — its "talent level" tree, one node per ability */
export function talents(tierSpec){
  if (!tierSpec || !Array.isArray(tierSpec.may)) return "";
  const all = ["think", "compute", "prove", "notebook_write", "notebook_read", "notebook_list",
               "recall", "claim", "submit", "rest", "amend", "spawn", "author_task", "hermes_quest"];
  return `<div class="talents">` +
    all.map(a => {
      const held = tierSpec.may.includes(a);
      const locked = (a === "hermes_quest");  /* held only by operator grant */
      const cls = held ? (locked ? "granted" : "held") : "locked";
      return `<span class="talent ${cls}" title="${a}">${esc(a.replace(/_/g, " "))}</span>`;
    }).join("") +
    `</div>`;
}
