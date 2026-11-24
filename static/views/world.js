/* WORLD — the machine MIST lives on. The landing view.
 * GET /api/world : self, kin, memory, skills, sessions, delegations, cron,
 * world (the company), the colony read-through, and the charter.
 */
import {
  state, paint, esc, dsh, has, num, f2, secsOf, clockOf, agoOf,
  chip, barrow, bar, kv, panel, table, empty, note,
  errbox, hyper, sourceTag, staleTag,
} from "../app.js";

export let lastRender = 0;

export function mount(ctx){ render(ctx); }
export function update(ctx){ render(ctx); }

function render(ctx){
  const w = state.world;
  if (!w){
    paint(ctx.root, panel("world",
      state.worldErr ? errbox(state.worldErr) + note("The console cannot read the world right now. It will keep trying every 5s.")
                     : note("reading the world…"),
      {cls: "c12 " + (state.worldErr ? "bad" : "")}));
    return;
  }
  const parts = [];
  parts.push(errorsPanel(w));
  parts.push(selfPanel(w));
  parts.push(kinPanel(w));
  parts.push(memoryPanel(w));
  parts.push(colonyPanel(w));
  parts.push(skillsPanel(w));
  parts.push(sessionsPanel(w));
  parts.push(companyPanel(w));
  parts.push(cronPanel(w));
  parts.push(delegationsPanel(w));
  parts.push(charterPanel(w));
  paint(ctx.root, parts.filter(Boolean).join(""));
}

/* --------------------------------------------------------------- sections */

function errTag(at, err){
  const now = Date.now();
  if (err) return sourceTag(at, err, now);
  return staleTag(at, now);
}

function errorsPanel(w){
  if (!w.errors || !w.errors.length) return "";
  return panel("sources that failed", `<pre>${esc(w.errors.join("\n"))}</pre>`,
    {cls: "c12 bad", meta: `${w.errors.length} of the aggregator's sources`});
}

function selfPanel(w){
  const sf = w.self || {};
  const gw = sf.gateway || {};
  const all = sf.all_gateways || {};
  const rows = Object.keys(all).map(k => [
    esc(k),
    all[k] && all[k].pid ? chip("pid " + esc(all[k].pid), "on") : chip("not running", "off"),
    dsh(all[k] ? all[k].last_exit : null),
  ]);
  const body =
    kv("name", `<b>${dsh(sf.name)}</b>`) +
    kv("profile", dsh(sf.profile)) +
    kv("model", dsh(sf.model)) +
    kv("provider", dsh(sf.provider)) +
    kv("host", dsh(sf.host)) +
    kv("hermes home", dsh(sf.hermes_home)) +
    kv("gateway service", dsh(sf.gateway_service)) +
    kv("gateway", gw.pid ? chip("pid " + esc(gw.pid), "on") : chip("down", "off") +
       (has(gw.last_exit) ? " " + chip("exit " + esc(gw.last_exit), gw.last_exit === "0" ? "" : "warnb") : "")) +
    kv("version", dsh(sf.version)) +
    kv("gateway started", clockOf(sf.started)) +
    kv("console uptime", secsOf(sf.uptime_seconds)) +
    (rows.length ? `<div style="margin-top:7px"><div class="note">all hermes gateways</div>` +
      table(["service", "state", "last exit"], rows, {scroll: "short", key: "gw"}) + `</div>` : "");
  return panel("me · self", body, {cls: "c4", meta: errTag(state.worldAt, null)});
}

function kinPanel(w){
  const kin = Array.isArray(w.kin) ? w.kin : [];
  if (!kin.length) return panel("chain of command", empty("no kin reported"), {cls: "c4"});
  const cards = kin.map(k => {
    const gw = k.gateway || {};
    return `<div class="card">
      <div class="cname">${dsh(k.name)} <span class="dim">· ${dsh(k.profile)}</span></div>
      <div class="crole">${dsh(k.role)}</div>
      <div style="margin-top:5px">
        ${chip(esc(k.kind || "?"), k.kind === "prime" ? "on" : "solid")}
        ${gw.pid ? chip("pid " + esc(gw.pid), "on") : (k.kind === "spawn" ? chip("pool", "solid") : chip("no gateway", "off"))}
        ${chip(esc(k.model || "model ?"))}
        ${k.provider ? chip(esc(k.provider)) : ""}
        ${k.skills ? chip(k.skills + " skills") : ""}
      </div></div>`;
  }).join("");
  return panel(`chain of command · ${kin.length}`, `<div class="stack">${cards}</div>`,
    {cls: "c4", meta: "everything on this host reports through me"});
}

function memoryPanel(w){
  const mem = w.memory || {};
  const blocks = ["memory", "user"].map(key => {
    const m = mem[key];
    if (!m) return "";
    const label = key === "memory" ? "my notes" : "who you are";
    if (m.error) return `<h3 class="dim" style="margin:6px 0 3px">${esc(label)}</h3>` + errbox(m.error);
    const p = m.limit ? m.chars / m.limit : 0;
    return `<h3 class="dim" style="margin:7px 0 3px">${esc(label)}</h3>` +
      barrow(esc(m.path ? m.path.split("/").pop() : label), m.chars, m.limit || null,
             {warn: .8, bad: .95, right: `${num(m.chars)} / ${num(m.limit)} chars`}) +
      `<div class="note">${num(m.entries)} entr${m.entries === 1 ? "y" : "ies"}${m.path ? " · " + esc(m.path) : ""}</div>` +
      `<div class="scrolly short" data-scroll="mem-${esc(key)}" style="margin-top:4px"><pre>${esc(m.text || "(empty)")}</pre></div>`;
  }).join("");
  return panel("memory", blocks || empty("no memory files reported"),
    {cls: "c4", meta: "what I hold across sessions"});
}

function colonyPanel(w){
  const c = w.colony || {};
  const now = Date.now();
  if (!c.up && !c.agents){
    return panel("the colony", (c.error ? errbox(c.error) : empty("colony database not present")) +
      `<div class="actions">${hyper("#/colony", "open colony →")}</div>`, {cls: "c4", meta: errTag(state.worldAt, null)});
  }
  const pop = c.population || {}, tiers = c.tiers || {}, work = c.work || {};
  const body =
    kv("tick", `<b class="mono">${num(c.tick)}</b>`) +
    kv("last turn", esc(c.last_tick_at || "—")) +
    kv("population", `<span class="chip on">${num(pop.active)} active</span><span class="chip">${num(pop.hibernating)} hibernating</span><span class="chip">${num(pop.retired)} retired</span>`) +
    kv("tiers", Object.keys(tiers).length
      ? Object.entries(tiers).map(([t, n]) => chip(esc(t) + " × " + n)).join("")
      : "—") +
    kv("work", `${num(work.solved)} verified / ${num(work.attempts)} attempts` +
       (work.accuracy != null ? ` · <b>${f2(work.accuracy, 1)}%</b>` : "") +
       ` · ${num(work.open_tasks)} open`) +
    (work.accuracy != null ? bar(work.accuracy / 100, {warn: .5, bad: .3}) : "") +
    kv("economy", `${num(Math.round(c.economy && c.economy.circulation || 0))} credits in circulation`) +
    kv("compute", `${num(c.tokens && c.tokens.this_tick)} tokens this tick · ${num(c.tokens && c.tokens.last_24h)} in 24h`) +
    kv("laws", num((c.laws || []).length)) +
    kv("petitions", c.petitions_pending
      ? `<span class="warnc">${num(c.petitions_pending)} waiting on me</span>`
      : num(0) + " pending") +
    (c.directive ? `<h3 class="dim" style="margin:8px 0 3px">my standing directive</h3><pre>${esc(c.directive)}</pre>` : "") +
    `<div class="actions">${hyper("#/colony", "open the colony →")}</div>`;
  return panel("the colony · at a glance", body, {cls: "c4", meta: errTag(state.worldAt, null)});
}

function skillsPanel(w){
  const sk = w.skills || {};
  if (sk.error) return panel("skills", errbox(sk.error), {cls: "c4"});
  const cats = Object.entries(sk.categories || {})
    .map(([k, n]) => chip(esc(k) + " " + n)).join("") || `<span class="dim">—</span>`;
  const items = (sk.items || []);
  const rows = items.map(i => [
    esc(i.category || "."), `<b>${esc(i.name)}</b>`,
    `<span class="wrap">${esc(i.description || "")}</span>`,
  ]);
  return panel(`skills · ${num(sk.total)} active`,
    `<div class="rowline" style="margin-bottom:6px">${cats}</div>` +
    (sk.archived ? `<div class="note">${num(sk.archived)} archived on disk, not loaded into context</div>` : "") +
    (rows.length ? table(["cat", "skill", "what it is for"], rows,
      {scroll: "short", key: "skills", empty: "no active skills"}) : empty("no active skills")),
    {cls: "c4", meta: `${num(sk.archived || 0)} archived`});
}

function sessionsPanel(w){
  const se = w.sessions || {};
  if (se.error && !se.totals) return panel("sessions", errbox(se.error), {cls: "c4"});
  const t = se.totals || {};
  const rows = (se.recent || []).map(r => [
    esc(r.started_ago || agoOf(r.started_at)),
    `<span class="wrap">${dsh(String(r.source || "").slice(0, 34))}</span>`,
    num(r.message_count), num(r.tool_call_count),
    num((Number(r.input_tokens) || 0) + (Number(r.output_tokens) || 0)),
  ]);
  const body =
    kv("sessions", `<b class="big">${num(t.sessions)}</b>`) +
    kv("messages", num(t.messages)) +
    kv("tool calls", num(t.tool_calls)) +
    kv("tokens in", num(t.input_tokens)) +
    kv("tokens out", num(t.output_tokens)) +
    (rows.length ? table(["started", "source", "msgs", "tools", "tok"], rows,
      {scroll: "short", key: "sess", empty: "no sessions"}) : empty("no sessions on record")) +
    (se.error ? `<div class="note">${esc(se.error)}</div>` : "");
  return panel("sessions", body, {cls: "c4", meta: "my own traffic on this host"});
}

function companyPanel(w){
  const wo = w.world || {};
  const q = wo.quorum_console || {};
  const tasks = wo.tasks || [], apps = wo.apps || [], procs = wo.processes || [];
  const le = q.latest_engagement;
  const body =
    `<div class="split2">` +
      `<div>` +
        kv("Company Control", q.up ? chip("up", "on") : chip("down", "off")) +
        kv("company", dsh(q.company)) +
        kv("profile", dsh(q.profile)) +
        kv("mode", q.mock == null ? "—" : (q.mock ? chip("mock", "warnb") : chip("live", "on"))) +
        kv("roster", num(q.roster)) +
        kv("running jobs", `${num(q.running_jobs)} ${q.busy ? chip("BUSY", "warnb") : ""}`) +
        kv("task threads", num(q.tasks)) +
        kv("events", num(q.events)) +
        kv("latest engagement", le
          ? `#${esc(le.id)} ${chip(esc(le.verdict || le.status || "?"))} <span class="dim">${esc(String(le.topic || "").slice(0, 70))}</span>`
          : "—") +
      `</div>` +
      `<div>` +
        `<div class="note">live apps</div>` +
        (apps.length ? apps.map(a => `<div class="card" style="margin-bottom:4px">` +
            chip("#" + esc(a.engagement_id), "on") + chip(":" + esc(a.port || "?")) + chip("pid " + esc(a.pid)) +
            `<div class="crole">${esc(a.url || a.name || "")}</div></div>`).join("")
          : empty("no apps running")) +
        `<div class="note" style="margin-top:7px">listening processes</div>` +
        (procs.length ? table(["cmd", "pid", "addr"], procs.map(p => [esc(p.command), esc(p.pid), esc(p.name)]),
            {scroll: "short", key: "proc"}) : empty("none visible")) +
      `</div>` +
    `</div>` +
    `<div style="margin-top:8px"><div class="note">task threads (${tasks.length})</div>` +
      table(["id", "rev", "status", "owner", "title"],
        tasks.map(t => [esc(t.id), "v" + esc(t.revision), chip(esc(t.status || "?")),
                        esc(t.agent_id || "—"), `<span class="wrap">${esc(String(t.title || "").slice(0, 80))}</span>`]),
        {scroll: "short", key: "wtasks", empty: "no task threads"}) +
    `</div>`;
  return panel("the company I operate", body, {cls: "c12", meta: "Company Control on :8787"});
}

function cronPanel(w){
  const cr = w.cron || {};
  const jobs = cr.jobs || [];
  const rows = jobs.map(j => [
    `<b>${esc(j.name || j.id || "unnamed")}</b>`,
    `<span class="wrap">${esc(j.schedule || "—")}</span>`,
    j.enabled ? chip("on", "on") : chip("off", "off"),
    j.no_agent ? chip("script", "solid") : chip("agent", "infob"),
    esc(j.script || "—"),
    esc(j.target || "—"),
    j.last_run ? esc(agoOf(j.last_run)) : "—",
  ]);
  return panel(`scheduled work · ${num(cr.count != null ? cr.count : jobs.length)}`,
    (rows.length ? table(["job", "schedule", "on", "kind", "script", "→", "last run"], rows,
      {scroll: "short", key: "cron", empty: "nothing scheduled"}) : empty("nothing scheduled")) +
    (cr.error ? `<div class="note">${esc(cr.error)}</div>` : ""),
    {cls: "c4", meta: "cron / interval work I run myself"});
}

function delegationsPanel(w){
  const dg = w.delegations || {};
  const rows = dg.rows || [];
  if (!rows.length) return panel("spawned workers", empty("none in flight") +
    (dg.error ? `<div class="note">${esc(dg.error)}</div>` : ""), {cls: "c4"});
  const cards = rows.map(r => `<div class="card">
    <div class="cname">${esc(r.goal || r.title || r.id || "(worker)")}</div>
    <div class="crole">${[r.status, r.mode, r.model].filter(Boolean).map(esc).join(" · ") || "—"}</div>
    ${r.goals ? `<div class="crole">${esc(r.goals)}</div>` : ""}
    ${r.created_at ? `<div class="crole dim2">${esc(agoOf(r.created_at))}</div>` : ""}
  </div>`).join("");
  return panel(`spawned workers · ${rows.length}`, `<div class="stack">${cards}</div>`,
    {cls: "c4", meta: dg.error ? chip("partial", "warnb") : "delegations"});
}

function charterPanel(w){
  const ch = w.charter || {};
  return panel("the standing order",
    (ch.error ? errbox(ch.error) : "") +
    `<div class="note" style="margin-bottom:4px">${esc(ch.path || "")}</div>` +
    `<div class="scrolly" data-scroll="charter" style="max-height:340px"><pre>${esc(ch.text || "(empty)")}</pre></div>`,
    {cls: "c8", meta: "MIST's charter"});
}
