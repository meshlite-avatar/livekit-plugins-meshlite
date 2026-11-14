# Example: a Pipecat bot with a MeshLite face

A complete local demo, started with one command:

```bash
cd examples/pipecat-browser-avatar
cp .env.example .env      # Windows: copy .env.example .env
# open .env and fill it in (see "Prepare your accounts")
python run.py
```

`run.py` does the rest, on Windows, macOS and Linux (Python 3.11 or later, as Pipecat
requires):

1. creates a virtual environment in `.venv` and installs `requirements.txt` (first run only);
2. checks `.env` and lists what is missing or wrong, without ever printing a value;
3. starts `bot.py`, with its logs prefixed `[bot]`;
4. opens http://localhost:8080 (the `PORT` from `.env`);
5. stops it on Ctrl+C.

Press **Start** in the page and allow the microphone. The avatar greets you and answers
with matching lips. Interrupt it by speaking: it stops at once.

Options: `python run.py --check` only checks `.env`; `--no-browser` does not open the
page; `--no-install` leaves the virtual environment alone.

| File | Role |
|---|---|
| `run.py` | one-command launcher (virtual environment, `.env` check, start, clean stop) |
| `bot.py` | one small server: the page, the MeshLite session token (`audio: "track"`) and a Pipecat bot per visitor (SmallWebRTC, OpenAI or Azure OpenAI realtime model) |
| `index.html` | the visitor page: mounts the avatar, connects the Pipecat client, hands the bot to the avatar with `avatar.attachPipecat(client)` |

Nothing MeshLite-specific runs in the bot: no plugin, no extra participant. The page gives
the bot's audio track to the MeshLite web SDK, which animates the face in the browser and
follows Pipecat's speaking and interruption events. See the
[Pipecat guide](https://meshlite.io/docs#pipecat) for the details.

## Prepare your accounts

- **MeshLite Console** (Projects, then **For developers**): in **Allowed sites**, add
  `http://localhost:8080` as a test site; in **Keys**, create a test publishable key and a
  test secret key; in **Code**, copy your avatar id.
- **OpenAI**: an API key for the example bot (`OPENAI_API_KEY`). `OPENAI_REALTIME_MODEL`
  picks another realtime model; or swap in any other Pipecat pipeline in `bot.py`
  (speech-to-text, LLM and voice services work the same way).
- **Azure OpenAI instead of OpenAI**: deploy a realtime model in your Azure resource, then
  uncomment the three `AZURE_OPENAI_*` lines in `.env` (endpoint such as
  `https://my-resource.openai.azure.com`, key, deployment name). When `AZURE_OPENAI_ENDPOINT`
  is set, the bot uses Azure and `OPENAI_API_KEY` is not needed. If your resource restricts
  network access, allow the machine that runs the bot.

No LiveKit, Daily or other media server is needed: the browser and the bot talk directly
over WebRTC.

## What you should see

```
[run] Starting the bot (the first start takes a few seconds) ...
[run] Ready: http://localhost:8080
[run] Press Start in the page and allow the microphone. Press Ctrl+C here to stop.
[bot] INFO    Visitor connected: the bot greets them.
```

In the page: "Connecting...", then "Avatar ready (voice played by the frame)" on Chrome or
Safari, or "(voice played by the page)" on Firefox. The face then greets you.

The face starts speaking about 0.6 s after the voice reaches the page: a live track gives no
"segment ready" signal, so the avatar needs a little audio before its lips can move. Until
the face is ready, the page plays the voice itself, so the visitor never waits for the face.

On Firefox the page plays the voice itself and the avatar moves its lips in silence, so
Firefox's echo cancellation hears the voice; other browsers play it in the avatar frame.

## Run it yourself

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

## Troubleshooting

- **`.env` problems**: `python run.py --check` names each missing setting.
- **"meshlite_session_refused"**: the publishable key, secret key, avatar id and
  `PUBLIC_ORIGIN` must belong to the same environment (test or live), and the origin must be
  declared as a site in the MeshLite console.
- **No voice on the page**: click **Enable sound** if it appears (browsers need a click
  before they play sound).
- **The bot does not answer**: check `OPENAI_API_KEY` (or the `AZURE_OPENAI_*` settings) and
  the `[bot]` lines for errors. `403 ... Virtual Network/Firewall rules` from Azure means the
  resource does not allow this machine's address.
- **"Avatar unavailable"**: the voice continues without the face (fallback); the code in the
  message says why (for example `SDK_UPGRADE_REQUIRED` for an SDK older than 1.11.48).
- **Port already in use**: change `PORT` in `.env` (and declare the new address as a site).

## Going live

- Use live keys and declare your HTTPS domain in the MeshLite console (`PUBLIC_ORIGIN`).
- Authenticate your visitors and rate-limit `/api/session` (it creates a conversation) and
  `/api/offer` (it starts a bot).
- SmallWebRTC connects the browser straight to your server: behind a firewall or NAT, add a
  STUN or TURN server, or use Daily or another Pipecat transport. The page code stays the
  same apart from the transport (`attachPipecat` works with any of them).
