# MIST console — frozen API contract

The UI is built against these endpoints and nothing else. The backend implements
exactly this. All responses are JSON. GETs are observational except `GET /api/pantheon`, which starts the bounded autonomous world builder once per server process. Model-spending POSTs and the asset builder use the free OpenCode Go relay; persistent world additions are written only to the console's own SQLite store.

Base URL: `http://127.0.0.1:8790`

## GET /api/health
`{"ok": true}`

## GET /api/world
The machine MIST lives on. Keys:
- `generated` (str), `errors` (list of str — sources that failed)
- `self` — `{name, profile, model, provider, host, hermes_home, gateway_service, gateway:{pid,last_exit}, version, all_gateways:{...}, uptime_seconds}`
- `kin` — list of `{kind: prime|sibling|spawn, profile, name, role, model, provider, gateway:{pid}, skills}`
- `memory` — `{memory:{path,text,chars,limit,entries}, user:{...}}`
- `skills` — `{total, archived, categories:{name:count}, items:[{name,category,description,path}]}`
- `sessions` — `{totals:{sessions,messages,tool_calls,input_tokens,output_tokens}, recent:[{id,source,model,started_at,ended_at,message_count,tool_call_count,input_tokens,output_tokens,started_ago}]}`
- `delegations` — `{rows:[...], error}`
- `cron` — `{jobs:[{id,name,schedule,enabled,no_agent,script,target,last_run}], count}`
- `world` — `{quorum_console:{up,company,profile,roster,running_jobs,busy,tasks,events,latest_engagement}, tasks:[...], apps:[...], processes:[{command,pid,name}]}`
- `colony` — as `GET /api/colony` (below)
- `charter` — `{path, text}`

## GET /api/colony
The world view of the colony. Keys:
- `up` (bool), `tick` (int), `last_tick_at` (str), `directive` (str — MIST's standing order)
- `population` — `{active, hibernating, retired}`
- `tiers` — `{architect:2, specialist:2, worker:2}`
- `agents` — list of, per CI:
  `{id, name, tier, domain, generation, credits, fitness, tasks_attempted, tasks_verified,
    failures_streak, status, born_tick, last_tick, cadence, phase, temperature, curiosity,
    parent_id,
    doing: {task_id, domain, difficulty, question, reward, claimed_tick} | null,
    last_call: {at, model, tier, tokens, ms, ok} | null,
    brain: {memory, instruments, submissions, ledger_rows}}`
- `work` — `{solved, attempts, accuracy, open_tasks}`
- `economy` — `{circulation}`
- `tokens` — `{this_tick, last_24h}`
- `budgets` — `{tick, day}`
- `laws` — `[{id, text, status, enacted_tick, proposed_tick, votes, mist_veto}]`
- `chronicle` — `[{tick, kind, agent_id, text}]` newest first, ~40
- `petitions` — `[{id, tick, agent_id, kind, body, status}]`, plus `petitions_pending` (int)
- `ledger` — `[{tick, agent_id, delta, reason, balance}]` newest first, ~20
- `tasks` — the pool: `[{id, domain, difficulty, reward, status, claimed_by, claimed_by_name, claimed_tick, solved_tick, question, attempts, authored_by}]`
- `models` — `{reflex, worker, specialist, architect}` — which model each tier runs
- `roster_health` — `{no_commit_last_tick, failures_last_tick, verified_last_tick}`

## GET /api/pantheon
Embodied scene state. Keys:
- `clock`, `agents`, `minds`, `talk` — current in-world clock, CI bodies, optional metered-brain flag, and recent speech.
- `places` — fixed civic/domain places plus persistent generated places.
- `artifacts` — console-owned `workboard` records generated from each CI's actual task, recent instrument output, memory, and affect cues. No colony DB writes.
- `assets` — validated model-designed real-world objects, attributed to their owner/profile and model, with placement, dimensions, zero-cost billing metadata and source tick.
- A repeated attendee pair (two or more saved meetings) generates a stable `social` pavilion inside the walkable town, with participant names, interaction count, and reason. Assemblies refresh the generator; its output is persisted in `data/console.db`.
- Opening Pantheon starts Vinod Chanda (`cc-operator`)'s bounded autonomous asset builder: one build immediately, then at most one per 15 minutes. Only the console DB is written; the Colony is read-only. The builder refuses any response not billed as OpenCode Go at zero cost.

## GET|POST /api/pantheon/minds
POST `{"on": true|false}` toggles minds. Both return `{minds, agents, model, think_interval, daily_token_cap, tokens_24h, calls_this_process, backoff_until, last_error}`.

## GET /api/pantheon/minds/log?name=&limit=
`{status, log:[{id, ts, name, model, ok, error, tokens, ms, observation, thought, goal, action, outcome}], episodes:[{ts, kind, text, salience}]}` newest first. `observation` is exactly what the CI was shown for that decision.

Pantheon bodies additionally carry `goal`, `thought`, `path` (a routed polyline while moving, else null), `depart_at`, `arrive_at`; the snapshot carries `clock.now` and `layout` — `{colliders:[box{x0,z0,x1,z1}|circle{x,z,r}], openings, trees, roads}`.

## GET /api/research · POST /api/research/<id>/approve · POST /api/research/<id>/reject
Residents' research/build proposals. `approve` starts a Quorum engagement (503 if Company Control is not reachable, 409 unless pending); `reject` takes `{"reason"}`. Rows: `{id, ts, name, kind, topic, why, status: pending|running|done|rejected|failed, job_id, engagement_id, verdict, paper_path, summary, error}`.

`GET /api/pantheon/minds/log?name=` also returns `life: {needs, plan, goal, relations, research}`; log rows carry `kind` (moment|converse|plan|reflect) and `locality` (local|cloud).

## GET /api/world-builder
Returns `{owner, profile, model, assets, interval_seconds, autobuilder_started, last_build_started}`. The assets are newest first.

## POST /api/world-builder/build
Body `{"brief":"Add a compact electric car for the residents"}` (1–500 characters). Makes one bounded OpenCode Go model call, validates the design and safe dimensions, assigns a collision-free site, and persists an immutable attributed asset. Response `{asset, model, cost, tokens}`. The server refuses to persist unless OpenCode reports `billing_source=go` and `cost=0`.

## GET /api/ci/<name>
One CI, opened up. `<name>` is case-insensitive. 404 `{"error":"no such CI"}` if absent.
- `agent` — every column of the CI's row (id, name, tier, domain, generation, credits, fitness,
  tasks_attempted, tasks_verified, failures_streak, temperature, curiosity, session_id, status,
  hibernating_since, born_tick, last_tick, cadence, phase, parent_id)
- `tier` — the tier's spec: `{level, model, max_tokens, tool_rounds, temperature, may:[...]}`
- `identity` — `{name, tier, domain, generation, world_note, instruments:[...]}`
- `memory` — `[{id, tick, kind, text, salience, origin_agent_id}]` newest first
- `notebook` — `{files:[{path, bytes, mtime}]}`
- `submissions` — `[{id, task_id, tick, answer, verified, verdict, score, detail}]` newest first
- `instruments` — `[{tick, name, args, result}]` newest first (the CI's own audit trail)
- `ledger` — `[{tick, delta, reason, balance}]` newest first
- `usage` — `[{tick, model, tier, ms, tokens, prompt_tokens, completion_tokens, ok, ts}]` newest first
- `events` — `[{tick, kind, text}]` where this CI is the subject
- `doing` — current claim or null
- `affect` — cautious, evidence-derived label + cues (never a claim of subjective feeling)
- `prompt_trace` — the exact recent memory IDs and task context selected by the prompt builder
- `interactions` — saved assemblies this CI attended, including peers and transcript
- `lineage` — `{parent:{id,name,tier} | null, children:[{id,name,tier,generation}]}`
- `thread` — saved conversations with MIST, newest first: `[{id, ts, question, reply, model, ms, tokens}]`

## GET /api/ci/<name>/note?path=<relative path>
`{path, text}` — one file out of the CI's own notebook. `{"error": "no such note"}` if absent.

## POST /api/ci/<name>/ask
Body `{"message": "..."}`. Runs ONE live model call (free tier model) with the CI's own
identity, memory, notebook and current task as context — the CI answers as itself.
Response: `{id, ci, question, reply, model, ms, tokens, ts}`
The exchange is appended to `/api/ci/<name>/thread`.
Errors: `{"error": "..."} ` with HTTP 400 (empty message) / 502 (model failed).

## POST /api/voice/<name>/turn
Body: raw mono PCM WAV (`audio/wav`), 16 kHz, 16-bit, maximum 60 seconds / 6 MB.
The server transcribes locally with whisper.cpp, sends only the transcript through the same
CI ask path above, and synthesizes the reply locally with the Kokoro ONNX voice assigned to
that CI. Response has the saved exchange fields plus `transcript`, `audio_mime: "audio/wav"`,
`voice_name`, `voice_label`, and `audio_base64`; an optional `voice_error` means the text
reply succeeded but local speech synthesis did not. Raw input audio is held in a temporary
file during transcription and deleted immediately. It is never uploaded to the CI model or
kept in the console store.

## GET /api/assemblies
`{"assemblies": [{id, kind, topic, created, cis, rounds, status, speakers, transcript_len,
spend}], "stats": {exchanges, assemblies, tokens_spent}}` — newest first.
(An earlier revision of this contract said "bare array"; the implementation returns the
object above, and the UI accepts either shape. The object is the contract.)

## POST /api/assembly
Body `{"kind": "meeting"|"dinner"|"townhall", "topic": "...", "cis": ["Vesper","Kestrel"], "rounds": 1}`
- `townhall` — every CI answers the topic, in one round, no cross-talk.
- `meeting` — each CI speaks in turn, and every later speaker is shown what the earlier ones said (debate).
- `dinner` — loose conversation: no agenda, each CI speaks once, in character, and may agree,
  disagree or digress.
- `rounds` defaults: townhall 1, dinner 1, meeting 2 (max 3).
- Each CI speaks once per round; each speech is one live model call, with at most one bounded retry when a reply is clipped. Room prompts include attendees' actual work and record-derived affect cues; no private feelings are assumed. In-world assembly calls seat attendees in the Hall and publish only complete reply text as speech bubbles.

Response (also stored whole, retrievable at `/api/assembly/<id>`):
`{id, kind, topic, created, status:"complete"|"partial", rounds, cis:[names],
  participants:[{name, tier, domain, model, fitness, credits, work, affect, affect_cues}],
  transcript:[{round, name, tier, model, text, ms, prompt_tokens, completion_tokens, tokens, retries, recovered, ok, error, ts}],
  closing:"...", spend:{calls, tokens}}`
A clipped reply is retried once and checked for a complete sentence. Any incomplete tail is withheld; if there is no complete sentence after recovery, its transcript `text` is empty and `ok` is false. The assembly status is `partial` when at least one speaker has no complete reply.

## GET /api/assembly/<id>
The same object. 404 if unknown.

## GET /api/static/<path>
Serves the UI's own files: `app.js`, `style.css`, `views/*.js`.

## GET /api/mist — MIST acts (the god's write path)
The operating commands plus the state they act on. Keys:
- `tick`, `directive` (the standing directive), `reach` (bool|null — may architects borrow a Hermes agent)
- `petitions` — pending petitions: `[{id, tick, agent_id, kind, body, status}]`
- `reviews` — tasks awaiting verdict: `[{id, domain, difficulty, reward, claimed_by_name, question}]`
- `roster` — `[{name, tier, domain, credits, fitness}]`
- `actions` — the accepted action names

## POST /api/mist/act — run one operating command
Body `{action: "<name>", ...fields}`. Actions and their fields:
- `petition-approve` / `petition-reject` — `{id}`
- `note` — `{text}` · `note-clear` — `{}`
- `grant` — `{agent, credits, reason?}`
- `spawn` — `{agent}`
- `reach-on` / `reach-off` / `reach-status` — `{}`
- `judge-accept` / `judge-reject` — `{task}`
- `dispatch` — `{brief}` (spends tokens; prose briefs land in reviews)
Response: `{ok, code, stdout, stderr, data, menu}` where `menu` is the refreshed
`GET /api/mist` payload. This is the one deliberate write path in a read-only console:
each action runs the real `colony` CLI in a subprocess.
