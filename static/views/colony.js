/* COLONY — the world, not the ledger.
 * A field of beings (each a sigil, a presence, a temperament, and its own words), with the
 * world's vitals around it. GET /api/colony.
 */
import {
  state, paint, esc, dsh, has, num, f2, msOf,
  chip, bar, barrow, kv, panel, table, empty, note, errbox,
  hyper, loadColony, sourceTag, colonyData,
} from "../app.js";
import { beingCard } from "../being.js";

export function mount(ctx){
  if (!state.colony) loadColony();
  render(ctx);
}
export function update(ctx){ render(ctx); }

function render(ctx){
  const c = colonyData();
  const err = state.colonyErr;
  if (!c || (!c.up && !c.agents)){
    paint(ctx.root, panel("colony",
      err ? errbox(err) : (c && c.error ? errbox(c.error) : note("reading the colony…")),
      {cls: "c12 " + (err || !c ? "bad" : "")}));
    return;
  }
  paint(ctx.root, [
    hero(c, err),
    fieldPanel(c),
    populationPanel(c),
    workPanel(c),
    economyPanel(c),
    computePanel(c),
    tasksPanel(c),
    lawsPanel(c),
    chroniclePanel(c),
    petitionsPanel(c),
    ledgerPanel(c),
  ].filter(Boolean).join(""));
}

/* ---------------------------------------------------------------- the beings */
function hero(c, err){
  const rh = c.roster_health || {};
  const idle = (Number(rh.no_commit_last_tick) || 0) + (Number(rh.failures_last_tick) || 0);
  const meta = (state.colonyErr
    ? sourceTag(state.colonyAt, state.colonyErr, Date.now())
    : sourceTag(state.colonyAt, null, Date.now()));
  const body =
    `<div style="font-size:30px;font-weight:700;letter-spacing:.01em">The colony</div>` +
    `<div class="mindmeta" style="margin-top:4px">tick ${num(c.tick)} · ${num(c.population?.active || 0)} beings · a society of Cloud Intelligences that woke up here — not uploaded from anywhere</div>` +
    (c.directive ? `<div class="mindline" style="margin-top:9px">“${esc(c.directive)}”</div>` : "") +
    `<div class="rowline" style="margin-top:9px">` +
      chip(`tick ${num(c.tick)}`, "on") +
      (c.last_tick_at ? chip("last turn " + esc(c.last_tick_at)) : "") +
      (rh.verified_last_tick ? chip(num(rh.verified_last_tick) + " verified last turn", "on") : "") +
      (idle ? chip(num(idle) + " idle or failing last turn", "warnb") : "") +
    `</div>`;
  return panel("the colony", body, {cls: "c12 " + (err ? "warn" : "good"), meta});
}

function fieldPanel(c){
  const agents = (c && Array.isArray(c.agents)) ? c.agents : [];
  if (!agents.length) return panel("citizens", empty("no CIs in the colony"), {cls: "c12"});
  return panel(`citizens · ${agents.length}`,
    `<div class="field">${agents.map(a => beingCard(a, {size: 78})).join("")}</div>` +
    `<div class="note" style="margin-top:6px">click a being to enter its mind.</div>`,
    {cls: "c12", meta: "each one lives — working, thinking, resting"});
}

/* ---------------------------------------------------------------- vitals (kept) */
function populationPanel(c){
  const pop = c.population || {}, tiers = c.tiers || {};
  const agents = c.agents || [];
  const total = agents.length || 1;
  const body =
    barrow("active", pop.active || 0, total, {right: `${num(pop.active)} / ${num(agents.length)}`}) +
    barrow("resting", pop.hibernating || 0, total, {right: num(pop.hibernating)}) +
    barrow("retired", pop.retired || 0, total, {right: num(pop.retired)}) +
    `<div class="rowline" style="margin-top:6px">` +
    Object.entries(tiers).map(([t, n]) =>
      chip(`<span class="tier-${esc(t)}">${esc(t)}</span> × ${n}`)).join("") + `</div>`;
  return panel("population", body, {cls: "c3", meta: `${num(agents.length)} CIs`});
}

function workPanel(c){
  const w = c.work || {};
  const acc = w.accuracy;
  const body =
    kv("verified", `<b class="big">${num(w.solved)}</b>`) +
    kv("attempts", num(w.attempts)) +
    kv("accuracy", acc == null ? "—" : `<b class="${acc >= 60 ? "ok" : acc >= 35 ? "warnc" : "badc"}">${f2(acc, 1)}%</b>`) +
    (acc == null ? "" : bar(acc / 100, {warn: .5, bad: .3})) +
    kv("open tasks", `<b>${num(w.open_tasks)}</b>`);
  return panel("work", body, {cls: "c3", meta: "submissions against the pool"});
}

function economyPanel(c){
  const led = (c.ledger || []).slice(0, 6);
  const body =
    kv("circulation", `<b class="big">${num(Math.round((c.economy || {}).circulation || 0))}</b>`) +
    `<div class="note" style="margin:5px 0 3px">latest movements</div>` +
    (led.length ? led.map(l => `<div class="kv"><span class="k">t${num(l.tick)}</span>` +
      `<span class="v mono"><span class="${l.delta > 0 ? "ok" : "badc"}">${l.delta > 0 ? "+" : ""}${num(l.delta)}</span> ` +
      `<span class="dim">${esc(String(l.reason || "").slice(0, 44))}</span></span></div>`).join("")
      : empty("no ledger entries"));
  return panel("economy", body, {cls: "c3", meta: "credits in circulation"});
}

function computePanel(c){
  const t = c.tokens || {}, b = c.budgets || {};
  const usedTick = Number(t.this_tick) || 0, usedDay = Number(t.last_24h) || 0;
  const body =
    kv("this tick", `<b>${num(usedTick)}</b> tokens`) +
    (b.tick != null ? barrow("tick budget", usedTick, b.tick, {warn: .8, bad: .95, right: `${num(usedTick)} / ${num(b.tick)}`})
        : bar(0, {thin: true}) + `<div class="note">no tick budget reported</div>`) +
    kv("last 24h", `<b>${num(usedDay)}</b> tokens`) +
    (b.day != null ? barrow("day budget", usedDay, b.day, {warn: .8, bad: .95, right: `${num(usedDay)} / ${num(b.day)}`})
        : bar(0, {thin: true}) + `<div class="note">no day budget reported</div>`) +
    `<div class="note" style="margin-top:5px">tier models</div>` +
    Object.entries(c.models || {}).map(([k, v]) => kv(k, esc(v))).join("");
  return panel("compute burned", body, {cls: "c3", meta: "against budget"});
}

/* ---------------------------------------------------------------- the pool & record (kept) */
function tasksPanel(c){
  const tasks = c.tasks || [];
  const rows = tasks.map(t => [
    chip("t" + esc(t.id), t.status === "open" ? "on" : (t.status === "solved" ? "solid" : "")),
    esc(t.domain), num(t.difficulty), num(t.reward),
    t.status === "open" ? chip("open", "on") : chip(esc(t.status || "?"), ""),
    t.claimed_by_name ? hyper("#/ci/" + encodeURIComponent(t.claimed_by_name), t.claimed_by_name)
      : (t.claimed_by != null ? esc(t.claimed_by) : "—"),
    num(t.attempts),
    `<span class="wrap" title="${esc(t.question || "")}">${esc(String(t.question || "").slice(0, 90))}</span>`,
  ]);
  return panel(`task pool · ${tasks.length}`,
    table(["task", "domain", "diff", "reward", "status", "held by", "att", "question"],
      rows, {scroll: "tall", key: "tasks", empty: "the pool is empty"}),
    {cls: "c7", meta: `${num((c.work || {}).open_tasks)} open`});
}

function chroniclePanel(c){
  const rows = (c.chronicle || []).map(e => [
    `<span class="mono dim">${num(e.tick)}</span>`,
    chip(esc(e.kind || "?")),
    e.agent_id != null ? esc(e.agent_id) : "—",
    `<span class="wrap">${esc(e.text || "")}</span>`,
  ]);
  return panel("chronicle", table(["tick", "kind", "CI", "what happened"], rows,
    {scroll: "tall", key: "chronicle", empty: "nothing recorded yet"}),
    {cls: "c5", meta: "newest first"});
}

function lawsPanel(c){
  const laws = c.laws || [];
  const cards = laws.map(l => `<div class="card">
    <div class="crole">#${esc(l.id)} ${chip(esc(l.status || "?"), l.status === "enacted" ? "on" : (l.status === "rejected" ? "off" : "warnb"))}
      ${chip("enacted t" + esc(l.enacted_tick == null ? "—" : l.enacted_tick))}
      ${l.mist_veto ? chip("vetoed by me", "off") : ""}</div>
    <div style="margin-top:4px;color:var(--ink2)">${esc(l.text || "")}</div>
  </div>`).join("");
  return panel(`laws they live under · ${laws.length}`,
    laws.length ? `<div class="stack">${cards}</div>` : empty("no laws enacted yet"),
    {cls: "c4", meta: "the colony's standing rules"});
}

function petitionsPanel(c){
  const ps = c.petitions || [];
  const cards = ps.map(p => `<div class="card">
    <div class="crole">#${esc(p.id)} ${chip("tick " + esc(p.tick))} ${chip(esc(p.kind || "?"))}
      ${chip(esc(p.status || "?"), p.status === "pending" ? "warnb" : (p.status === "granted" ? "on" : "off"))}
      ${p.agent_id != null ? chip("CI " + esc(p.agent_id)) : ""}</div>
    <div style="margin-top:4px;color:var(--ink2)">${esc(p.body || "")}</div>
  </div>`).join("");
  return panel(`petitions · ${num(c.petitions_pending)} pending`,
    cards ? `<div class="stack">${cards}</div>` : empty("no petitions"),
    {cls: "c4", meta: "what they ask of me"});
}

function ledgerPanel(c){
  const rows = (c.ledger || []).map(l => [
    `<span class="mono dim">${num(l.tick)}</span>`,
    l.agent_id != null ? hyper("#/ci/" + encodeURIComponent(l.agent_id), esc(l.agent_id)) : "—",
    `<span class="mono ${l.delta > 0 ? "ok" : "badc"}">${l.delta > 0 ? "+" : ""}${num(l.delta)}</span>`,
    `<span class="wrap">${esc(l.reason || "")}</span>`,
    `<span class="mono">${num(l.balance)}</span>`,
  ]);
  return panel("ledger", table(["tick", "CI", "delta", "reason", "balance"], rows,
    {scroll: "short", key: "ledger", empty: "no entries"}),
    {cls: "c4", meta: "newest first"});
}
