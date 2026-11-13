# livekit-plugins-meshlite

Give your [LiveKit Agents](https://docs.livekit.io/agents/) voice agent a lip-synced
[MeshLite](https://meshlite.io) face. Your agent keeps its own speech-to-text, LLM and
voice (or realtime model); MeshLite only renders the face, in the visitor's browser.

```
your agent (Python)  --lk.audio_stream-->  visitor page (livekit-client)  -->  MeshLite avatar (face + lips)
                     <--playback RPCs----
```

- No video server, no GPU, no extra participant in the room: the agent sends its voice to
  the visitor page over the LiveKit data channel, using the LiveKit Agents avatar
  data-stream protocol, and the MeshLite web SDK animates the avatar locally.
- Interruptions work as usual: the face stops at once and reports the position really
  heard, so the chat context keeps only what the visitor heard.
- No MeshLite voice minutes are used. The session still counts as a conversation
  (concurrent conversations, seats, statistics) and lasts at most 2 hours.

## Install

```bash
pip install livekit-plugins-meshlite
```

Requires Python 3.9+ and `livekit-agents` 1.x.

## Agent side

```python
from livekit.agents import Agent, AgentSession, JobContext
from livekit.plugins import meshlite

async def entrypoint(ctx: JobContext):
    await ctx.connect()
    session = AgentSession(stt=..., llm=..., tts=...)   # or a realtime model

    avatar = meshlite.AvatarSession()           # visitor_identity="..." if several visitors share the room
    await avatar.start(session, room=ctx.room)  # after ctx.connect(), before session.start()

    await session.start(agent=Agent(instructions="..."), room=ctx.room)
```

`AvatarSession.start()` waits for the visitor participant (the first standard participant,
or `visitor_identity`) and replaces the session audio output with LiveKit's
`DataStreamAudioOutput`. The agent then publishes no audio track: its voice reaches the
page as data and the MeshLite SDK plays it in sync with the face.

| Argument | Default | Meaning |
|---|---|---|
| `visitor_identity` | first standard participant | browser participant whose page shows the avatar |
| `sample_rate` | `24000` | PCM rate sent to the page (8000 to 48000) |
| `clear_buffer_timeout` | `2.0` | seconds to wait for the page to confirm an interruption |

### Audio format

One `lk.audio_stream` byte stream per speech segment: raw 16-bit signed little-endian PCM
(usually mono), 24 kHz by default, with `sample_rate` and `num_channels` stream attributes. The
agent sends the `lk.clear_buffer` RPC on interruption; the page answers with the
`lk.playback_started` and `lk.playback_finished` RPCs
(`{"playback_position": float, "interrupted": bool}`).

The data-stream protocol cannot pause and resume a segment. If your agent version offers
false-interruption resume, disable it: `AgentSession(..., resume_false_interruption=False)`.

## Browser side

You need a MeshLite account on a plan that can embed the SDK on a website, a declared
domain, a publishable key and a secret key of the same environment, and an avatar id
(all in the MeshLite console).

**1. Your server creates the MeshLite session** with `audio: "livekit"`. The secret key
stays on your server:

```js
const upstream = await fetch("https://console.meshlite.io/api/v1/client-sessions", {
  method: "POST",
  headers: { Authorization: `Bearer ${process.env.MESHLITE_SECRET_KEY}`, "Content-Type": "application/json" },
  body: JSON.stringify({
    publishableKey: process.env.MESHLITE_PUBLISHABLE_KEY,
    origin: "https://www.example.com",   // set by your server, never copied from the browser
    avatar: "your-avatar-id",
    audio: "livekit",
  }),
});
const { sessionToken } = await upstream.json();
```

**2. The visitor page mounts the avatar and attaches the room** before connecting:

```html
<div id="avatar" style="width:340px;height:510px"></div>
<script src="https://console.meshlite.io/sdk/1.11.46/meshlite.js" crossorigin="anonymous"></script>
<script type="module">
  import { Room } from "https://cdn.jsdelivr.net/npm/livekit-client@2.23.0/+esm";

  const avatar = MeshLite.mount({
    container: "#avatar",
    avatar: "your-avatar-id",
    publishableKey: "ml_pk_live_...",
    sessionToken,                                  // from your server (step 1)
    audio: "livekit",
  });

  const room = new Room();
  const link = avatar.attachLiveKit(room);         // attach before connect so no speech is missed
  link.on("ready", ({ output }) => console.log("avatar ready, voice played by", output));
  link.on("fallback", ({ code }) => console.warn("avatar unavailable, the voice continues", code));
  link.on("audio-blocked", () => showClickToEnableSound(() => link.resumeAudio()));

  await room.connect(LIVEKIT_URL, participantToken);  // your LiveKit token (data publishing allowed)
  await room.localParticipant.setMicrophoneEnabled(true);
</script>
```

Requirements: `livekit-client` 2.9 or later (tested with 2.23.0), MeshLite web SDK 1.11.45
or later, HTTPS (or `http://localhost` with test keys). Do not subscribe the agent audio
yourself: the SDK plays the voice.

`attachLiveKit(room, options)` accepts `agentIdentity` (accept audio only from this
participant), `output` (`"auto"`, `"frame"` or `"page"`) and `fallback` (default `true`).
With `output: "auto"`, Firefox plays the voice in your page while the avatar animates the
lips in silence, so Firefox's echo cancellation hears it; other browsers play it in the
avatar frame.

### Fallback: the avatar never blocks the conversation

When the face cannot start (refused session, network, timeout), fails, or is stopped
(maximum duration, quota), the page plays the agent voice itself from the position already
heard, the agent keeps receiving playback events and interruptions, and `link` emits
`fallback` with an error `code`. Use `fallback: false` to stop instead (`failed` /
`stopped` events).

## Limits

- Maximum session duration: 2 hours.
- LiveKit recordings (egress) do not contain the agent voice, since no audio track is
  published.
- The MeshLite avatar is not a room participant: `avatar.avatar_identity` on the agent side
  is the visitor identity.

## Example app

[`examples/browser-avatar`](examples/browser-avatar) is a complete local demo: a LiveKit
agent, a small Python server that creates both session tokens, and a page with the avatar.
Fill in its `.env` once, then one command does everything (virtual environment,
dependencies, `.env` check, agent and server together, browser, clean stop on Ctrl+C), on
Windows, macOS and Linux:

```bash
git clone https://github.com/meshlite-avatar/livekit-plugins-meshlite
cd livekit-plugins-meshlite/examples/browser-avatar
cp .env.example .env     # Windows: copy .env.example .env
# fill in .env: LiveKit, OpenAI, and your MeshLite test keys and avatar id
python run.py
```

See [its README](examples/browser-avatar/README.md) for the accounts to prepare and what
you should see.

## Development

```bash
pip install -e ".[test]"
pytest
```

The tests run offline with a fake room and check the exact protocol the MeshLite web SDK
implements.

## License

[Apache-2.0](LICENSE)
