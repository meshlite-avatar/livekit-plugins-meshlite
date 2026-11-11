# Example: a LiveKit agent with a MeshLite face

A complete local demo in three small files:

| File | Role |
|---|---|
| `agent.py` | LiveKit agent (OpenAI realtime model) whose voice is routed to the avatar by `livekit-plugins-meshlite` |
| `server.py` | serves the page and creates the LiveKit participant token and the MeshLite session token (`audio: "livekit"`) |
| `index.html` | the visitor page: mounts the avatar, attaches the LiveKit room, publishes the microphone |

## 1. Prepare your accounts

- **MeshLite console**: declare `http://localhost:8080` as a test domain, create a test
  publishable key and a test secret key, and copy your avatar id.
- **LiveKit**: a LiveKit Cloud project, or a local server started with `livekit-server --dev`.
- **OpenAI**: an API key for the example agent (or swap in any other model in `agent.py`).

## 2. Install

```bash
cd examples/browser-avatar
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then fill in .env
```

## 3. Run

In one terminal:

```bash
python agent.py dev
```

In another:

```bash
python server.py
```

Open http://localhost:8080, press **Start** and allow the microphone. The avatar greets
you and answers with matching lips. Interrupt it by speaking: it stops at once.

On Firefox the page plays the voice itself and the avatar moves its lips in silence, so
Firefox's echo cancellation hears the voice; other browsers play it in the avatar frame.

## Going live

- Use live keys and declare your HTTPS domain in the MeshLite console.
- Authenticate your visitors and rate-limit `/api/session`: it creates a conversation.
- Run the agent as a LiveKit worker (LiveKit Cloud or your own deployment).
