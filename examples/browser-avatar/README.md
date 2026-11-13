# Example: a LiveKit agent with a MeshLite face

A complete local demo, started with one command:

```bash
cd examples/browser-avatar
cp .env.example .env      # Windows: copy .env.example .env
# open .env and fill it in (see "Prepare your accounts")
python run.py
```

`run.py` does the rest, on Windows, macOS and Linux (Python 3.9 or later):

1. creates a virtual environment in `.venv` and installs `requirements.txt` (first run only);
2. checks `.env` and lists what is missing or wrong, without ever printing a value;
3. starts the agent and the web server together, with their logs prefixed `[agent]` and `[server]`;
4. waits for the agent to connect to LiveKit, then opens http://localhost:8080 (the `PORT` from `.env`);
5. stops both on Ctrl+C.

Press **Start** in the page and allow the microphone. The avatar greets you and answers
with matching lips. Interrupt it by speaking: it stops at once.

Options: `python run.py --check` only checks `.env`; `--no-browser` does not open the
page; `--no-install` leaves the virtual environment alone.

| File | Role |
|---|---|
| `run.py` | one-command launcher (virtual environment, `.env` check, agent + server, clean stop) |
| `agent.py` | LiveKit agent (OpenAI or Azure OpenAI realtime model) whose voice is routed to the avatar by `livekit-plugins-meshlite` |
| `server.py` | serves the page and creates the LiveKit participant token and the MeshLite session token (`audio: "livekit"`) |
| `index.html` | the visitor page: mounts the avatar, attaches the LiveKit room, publishes the microphone |

## Prepare your accounts

- **MeshLite Console** (Projects, then **For developers**): in **Allowed sites**, add
  `http://localhost:8080` as a test site; in **Keys**, create a test publishable key and a
  test secret key; in **Code**, copy your avatar id.
- **LiveKit**: a LiveKit Cloud project, or a local server. With
  [`livekit-server`](https://docs.livekit.io/home/self-hosting/local/) installed, set
  `LIVEKIT_URL=ws://localhost:7880`, `LIVEKIT_API_KEY=devkey` and `LIVEKIT_API_SECRET=secret`:
  `run.py` then starts `livekit-server --dev` for you and stops it with the rest.
- **OpenAI**: an API key for the example agent (`OPENAI_API_KEY`), or swap in any other model
  in `agent.py`.
- **Azure OpenAI instead of OpenAI**: deploy a realtime model in your Azure resource, then
  uncomment the three `AZURE_OPENAI_*` lines in `.env` (endpoint such as
  `https://my-resource.openai.azure.com`, key, deployment name). When `AZURE_OPENAI_ENDPOINT`
  is set, the agent uses Azure and `OPENAI_API_KEY` is not needed. If your resource restricts
  network access, allow the machine that runs the agent.

## What you should see

```
[run] Waiting for the agent to connect to LiveKit ...
[agent] registered worker
[run] The agent is connected to LiveKit and waits for a visitor.
[run] Ready: http://localhost:8080
[run] Press Start in the page and allow the microphone. Press Ctrl+C here to stop everything.
```

The page opens only once the agent is connected, so pressing Start never finds an empty room.

In the page: "Connecting...", then "Avatar ready (voice played by the frame)" on Chrome or
Safari, or "(voice played by the page)" on Firefox. The face then greets you.

On Firefox the page plays the voice itself and the avatar moves its lips in silence, so
Firefox's echo cancellation hears the voice; other browsers play it in the avatar frame.

## Run the pieces yourself

If you prefer two terminals (for example to edit `agent.py` with auto-reload):

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python agent.py dev              # terminal 1
python server.py                 # terminal 2
```

## Troubleshooting

- **`.env` problems**: `python run.py --check` names each missing setting.
- **"meshlite_session_refused"**: the publishable key, secret key, avatar id and
  `PUBLIC_ORIGIN` must belong to the same environment (test or live), and the origin must be
  declared as a domain in the MeshLite console.
- **No voice on the page**: click **Enable sound** if it appears (browsers need a click
  before they play sound), and check that the agent line `registered worker` is in the log.
- **The agent does not answer**: check `OPENAI_API_KEY` (or the `AZURE_OPENAI_*` settings),
  and the `[agent]` lines for errors. `403 ... Virtual Network/Firewall rules` from Azure means
  the resource does not allow this machine's address.
- **The page says it is connected but nobody answers, and the `[agent]` log is silent**: by
  default a LiveKit worker refuses new visitors while its machine's CPU is above 70 %, and the
  browser that draws the avatar often keeps a laptop that busy. This example turns that check
  off (`load_fnc=no_load` in `agent.py`). Keep it for local tests; remove it for a worker that
  runs alone on a server, so that LiveKit can spread visitors between workers.
- **Port already in use**: change `PORT` in `.env` (and declare the new address as a domain).

## Going live

- Use live keys and declare your HTTPS domain in the MeshLite console (`PUBLIC_ORIGIN`).
- Authenticate your visitors and rate-limit `/api/session`: it creates a conversation.
- Run the agent as a LiveKit worker (LiveKit Cloud or your own deployment): `python agent.py start`.
