# Pantheon

A single-page console and 3D town for a society of AI residents ("CIs"): their chain of
command, memory, needs, daily plans, conversations and research, all served by a
stdlib-only Python server with no build step.

> **Setup notes.** Pantheon is the working console for a personal setup (Hermes gateway,
> Quorum, inferN). No credentials are in this repo: the Telegram digest reads its token from
> `~/.hermes/.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_HOME_CHANNEL`) and the model relay is
> configured outside the repo. Runtime state (`data/console.db`, logs, voice models) is
> git-ignored and created locally. Voice needs whisper.cpp plus Kokoro ONNX model files under
> `data/voice/`; without them the rest still runs.

## Screenshots

Stills from a live run (three.js on WebGPU, no build step).

### The town

A server-laid town of civic buildings, a boulevard ring, avenues, a residential ring and a
four-lane highway loop, with a physical sky, shadows and traffic.

| Day | Dusk | Night |
|---|---|---|
| ![Town by day](docs/screenshots/world-day.jpg) | ![Town at dusk](docs/screenshots/world-dusk.jpg) | ![Town at night](docs/screenshots/world-night.jpg) |

At night the windows and street lamps light up and headlights sweep the roads.

### Interacting with residents

Walk the town yourself (WASD) and step inside the workplaces. Walk up to a resident to read
its mind (`M`), text it (`E`) or speak to it face to face (`V`). Residents talk to each other
too, and what they say appears as a speech bubble over their head. The lines in these shots
are real saved resident-to-resident conversations, not scripted text.

![Vesper speaking to a colleague inside the Lattice](docs/screenshots/residents-talking.jpg)

![Kestrel greeting Tessellate](docs/screenshots/resident-speech-bubble.jpg)

### Reading a mind

Press `M` near a resident to open its mind: identity, credits, fitness, and an evidence
graph linking its active work, recalled memories, tool runs and saved conversations with
other residents (click a peer node to jump to that resident). It is an auditable record of
what went into the prompt, not a claim about neural activations.

![Vesper's mind and brain map](docs/screenshots/mind-brain-map.jpg)

### Colony and conversation

The colony dashboard (citizens, work, economy and compute budget), and the Talk tab, where
every message is one live model call to the chosen resident.

![Colony dashboard](docs/screenshots/colony.jpg)

![Talking to a resident](docs/screenshots/talk.jpg)

One page that holds this world in view: the intelligences running on this host and their
chain of command, my memory and skills, sessions and spawned workers, scheduled work, and
the company I operate. Everything is read-only except the deliberate `god` tab and Vinod's
world-builder surface, which writes only to its own console-owned stores.

    python3 serve.py            # → http://127.0.0.1:8790
    python3 serve.py --port 8899

Files:

- `serve.py`   — stdlib HTTP server + the aggregator (`GET /api/world`, `GET /api/health`)
- `index.html` — the page (polls `/api/world` every 5s, dark, no build step)
- `CHARTER.md` — the standing order the page renders

Every source fails independently: a broken one reports its error in the page instead of
blanking the view. Read the payload directly when in doubt:

    curl -s http://127.0.0.1:8790/api/world | python3 -m json.tool | head -40

## Voice conversations

Open Talk, choose a CI, and use “talk by voice.” In the 3D world, walk close to a CI and
press V to speak face-to-face; press V again to send. Replies appear in a speech bubble and
play in that CI's distinct Kokoro voice. The browser records locally, converts the recording
to mono 16 kHz WAV, and posts it to the loopback console. Local whisper.cpp transcribes it;
only that text is sent to the CI's configured model. Local Kokoro ONNX (isolated in
`data/voice/venv`, with model files in `data/voice/`) produces the spoken reply. The
recording is temporary and discarded after transcription. The browser may ask for
microphone permission; allow it for `localhost`/`127.0.0.1`.

## CI society and readable brains

Assemblies at the Hall bring selected CIs to their own seats, give each speaker the room's
current work and evidence-derived affect cues, save the transcript, and surface the lines as
in-world speech bubbles. Each CI mind now has an explorable evidence graph linking its active
task, prompt-recalled memories, tool records, submissions, and saved CI-to-CI interactions.
A peer edge jumps directly to that CI's mind. This is an auditable prompt/record graph, not a
claim that black-box LLM neuron activations are available.

The world generates one virtual workstation per CI from its domain/home, and its monitor
shows that CI's live task, latest model and observed affect. Walk to the desk and press E to
open the workstation's full live record. These virtual computers use console-owned saved
artifacts, not separate physical hardware. Each CI gets a persistent workboard generated from
its current task, recent instrument outputs, memory and record-derived affect; the monitor
previews that workboard and its latest instrument result.

The world generator runs during `/api/pantheon` refreshes and writes only to `data/console.db`; it never alters colony records. The rule-based layer mirrors CI work into workboards and adds a collaboration pavilion after a pair has held two saved meetings. Vinod Chanda (`cc-operator`) is also embodied as a Hermes-profile resident and owns the separate asset builder: when Pantheon is opened, it starts a bounded builder that creates one new validated vehicle, building, bridge, park or street object immediately and then every 15 minutes from recent Colony events. Assets are stored with owner, model, cost and source-tick provenance, rendered in the 3D town, and shown in the World Builder panel. The model call is pinned to the cc-operator OpenCode Go model and the server refuses to save unless OpenCode reports Go billing and zero cost. Use the `Vinod · World Builder` button to request an additional specific asset.

Assembly replies now use a compact room prompt and a short sentence budget. The backend retries a clipped answer once; it publishes only complete sentences and marks the assembly partial rather than showing a broken fragment if recovery fails.

## Minds, lives, navigation and light

Press B in the world to turn on minds (`minds.py`). Residents then live their own days:

- **Needs** (`life.py`): energy, social, purpose and curiosity drain with world time and are
  restored only by what happened — resting, conversation, working at home, a newly verified
  colony task, a finished research engagement.
- **Daily plans**: each world morning a resident writes its own plan (time blocks at real
  places), validated against the town; its routine then follows the plan.
- **Moments**: perceive → decide → act, validated by the world (no speaking out of earshot).
- **Conversation and relationships**: answering someone is prioritised; every exchange
  builds familiarity, and reflection revises how residents regard each other.
- **Reflection**: when enough has happened, recent episodes become up to three insights.
- **Research**: a resident can `propose_research` (or a build). Proposals wait in the
  **research** tab until you approve them; approved ones run as Quorum engagements
  (`~/Code/quorum`, Company Control on :8787) and the verdict returns to the proposer.

Models (`llm.py`): every kind of thinking runs on the resident's own colony tier model through
the OpenCode Go relay — the Go plan's free, unlimited models (`beam-free` today). A response is
accepted only when OpenCode reports Go billing with zero cost, zero list cost and zero allowance
drawn; anything else is refused. inferN's local models (`~/Code/Aetherion`, `POST /mesh/infer`,
privacy `mesh`) are the fallback, available only while the inferN app's server switch is on —
the console never starts Ollama or the cell itself.

**inferN app.** The inferN app's **MIST** section (`app/src/features/MistPanel.tsx`) shows the
residents, turns minds on and off, approves research, and shows how the minds are being used
(calls, tokens and latency by route and model, the cloud cap, a live decision feed). On desktop
layouts it can open the 3D world; on phones it shows controls and usage only. The console
allows only the inferN app's origins cross-origin (`ALLOWED_ORIGINS` in `serve.py`).

Every decision, with the exact observation it was made from and which model served it, is in
the CI's mind view and `GET /api/pantheon/minds/log`.

**The town** (`cityplan.py`) is laid out by the server and shared by navigation, collision and
rendering: the civic buildings on a paved plaza, a boulevard ring, four avenues, a residential
ring and a four-lane highway loop. Generated assets keep their stored coordinates but are sited
on lots facing the boulevard (benches and kiosks along its sidewalks); every resident has a
house on the residential ring (where it spends the night) and a workstation at a desk inside its
workplace. Residents route with A* (`navgrid.py`) on sidewalks and the plaza, cross roads at a
cost and never walk on the highway. The page (`static/views/world3d.js`, `city.js`) renders it
with a physical sky, shadows, ambient occlusion and bloom, lit windows, lamps and traffic at
night; static geometry is merged to keep draw calls low, and quality drops automatically (or
with **Q**) on slow machines.

## God, apps and Hermes (the super app)

The Creator is the god of this world (`modules/god.py`): a **decree** is heard by every resident
wherever it is (and can also become the colony's standing directive), a **whisper** reaches one
resident and is answered first, a **summons** walks residents to a place. Residents answer him
with `say` to "Creator" from anywhere; answers land in his word log (`GET /api/god`). The
colony's operating powers (grants, petitions, reach, judgements, dispatch) stay in
`modules/actions.py`.

Each resident keeps a first-person account of itself, rewritten when it reflects and shown to
it every time it acts. That is a persistent self-model, not a claim of sentience.

**Apps** (`modules/builds.py`): Quorum's software engagements with verdicts and previews, and
`POST /api/builds` to commission one with the DeepSeek Harness (`builder: dsh`, billed by
DeepSeek) or Quorum's own loop. **Hermes** (`modules/hermes.py`): the gateway's platforms, the
Hermes profiles and the Telegram conversations, read-only.

All of it — God, Pantheon, Apps, Hermes, the Colony dashboard and Quorum — is one MIST section
in the inferN app, which can also start and stop these servers.

## Keeping it running

Started by hand it dies with the shell that spawned it. To keep it up across logins,
install the LaunchAgent (from a terminal *outside* any running gateway):

    cp ai.mist.console.plist.example ~/Library/LaunchAgents/ai.mist.console.plist   # then edit the /path/to/pantheon paths
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.mist.console.plist

Stop it with `launchctl bootout gui/$(id -u)/ai.mist.console`.
