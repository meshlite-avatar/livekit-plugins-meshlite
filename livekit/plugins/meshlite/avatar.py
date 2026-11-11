"""MeshLite avatar for LiveKit Agents.

The MeshLite avatar is not a participant of the room and the agent never
renders or publishes video. The visitor's web page shows the avatar with the
MeshLite web SDK (``audio: "livekit"`` + ``controller.attachLiveKit(room)``);
this module only routes the agent voice to that page.

Wire protocol (the LiveKit Agents avatar data-stream protocol):

* agent -> visitor: one ``lk.audio_stream`` byte stream per speech segment,
  16-bit PCM, ``sample_rate`` and ``num_channels`` stream attributes;
* agent -> visitor: RPC ``lk.clear_buffer`` on interruption;
* visitor -> agent: RPC ``lk.playback_started`` and ``lk.playback_finished``
  (``{"playback_position": float, "interrupted": bool}``).
"""

from __future__ import annotations

import inspect

from livekit import rtc
from livekit.agents import AgentSession, utils
from livekit.agents.voice.avatar import DataStreamAudioOutput

from .log import logger

DEFAULT_SAMPLE_RATE = 24000
_MIN_SAMPLE_RATE = 8000
_MAX_SAMPLE_RATE = 48000

try:
    _OUTPUT_PARAMS = inspect.signature(DataStreamAudioOutput.__init__).parameters
except (TypeError, ValueError):  # pragma: no cover - exotic builds
    _OUTPUT_PARAMS = {}


class AvatarSession:
    """Route an :class:`~livekit.agents.AgentSession` voice to a MeshLite avatar.

    Call :meth:`start` after ``await ctx.connect()`` and **before**
    ``await session.start(...)``: the agent then sends its voice to the
    visitor's page instead of publishing an audio track, and the page plays
    it in sync with the avatar's face.

    Args:
        visitor_identity: identity of the browser participant whose page
            shows the avatar. When omitted, the first standard (non-agent,
            non-SIP) remote participant of the room is used, which is the
            participant :class:`AgentSession` links to by default.
        sample_rate: PCM rate sent to the page. The page converts any rate;
            24 kHz matches the MeshLite engine and keeps the stream small.
        clear_buffer_timeout: seconds the agent waits for the page to confirm
            an interruption before it considers the speech stopped.
    """

    def __init__(
        self,
        *,
        visitor_identity: str | None = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        clear_buffer_timeout: float | None = 2.0,
    ) -> None:
        if visitor_identity is not None and (
            not isinstance(visitor_identity, str) or not visitor_identity.strip()
        ):
            raise ValueError("visitor_identity must be a non-empty string")
        if (
            isinstance(sample_rate, bool)
            or not isinstance(sample_rate, int)
            or not _MIN_SAMPLE_RATE <= sample_rate <= _MAX_SAMPLE_RATE
        ):
            raise ValueError(
                f"sample_rate must be an integer between {_MIN_SAMPLE_RATE} and {_MAX_SAMPLE_RATE}"
            )
        if clear_buffer_timeout is not None and not clear_buffer_timeout >= 0:
            raise ValueError("clear_buffer_timeout must be >= 0 or None")

        self._visitor_identity = visitor_identity
        self._sample_rate = sample_rate
        self._clear_buffer_timeout = clear_buffer_timeout
        self._audio_output: DataStreamAudioOutput | None = None
        self._agent_session: AgentSession | None = None
        self._starting = False
        self._closed = False

    @property
    def provider(self) -> str:
        return "meshlite"

    @property
    def visitor_identity(self) -> str | None:
        """Identity of the participant that renders the avatar (known after start)."""
        return self._visitor_identity

    @property
    def avatar_identity(self) -> str:
        """The participant whose page renders the avatar.

        MeshLite has no avatar participant: the avatar lives in the visitor's
        page, so this is the visitor identity.
        """
        if self._visitor_identity is None:
            raise RuntimeError("the visitor identity is known once start() has returned")
        return self._visitor_identity

    @property
    def audio_output(self) -> DataStreamAudioOutput | None:
        return self._audio_output

    async def start(self, agent_session: AgentSession, room: rtc.Room) -> None:
        if self._closed:
            raise RuntimeError("this MeshLite AvatarSession is closed")
        if self._starting or self._audio_output is not None:
            raise RuntimeError("MeshLite AvatarSession.start() can only be called once")
        self._starting = True
        try:
            identity = self._visitor_identity
            if identity is None:
                if not room.isconnected():
                    raise RuntimeError(
                        "connect to the room (await ctx.connect()) before starting the MeshLite "
                        "avatar, or pass visitor_identity"
                    )
                logger.debug("waiting for the visitor participant")
                participant = await utils.wait_for_participant(
                    room, kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD
                )
                identity = participant.identity
            if self._closed:
                raise RuntimeError("this MeshLite AvatarSession was closed while starting")

            previous = agent_session.output.audio
            if previous is not None:
                logger.warning(
                    "replacing the session audio output with the MeshLite avatar output; "
                    "call AvatarSession.start() before AgentSession.start() so the agent "
                    "does not publish its own audio track",
                    extra={"previous_output": getattr(previous, "label", type(previous).__name__)},
                )

            options: dict[str, object] = {}
            if "clear_buffer_timeout" in _OUTPUT_PARAMS:
                options["clear_buffer_timeout"] = self._clear_buffer_timeout
            if "wait_playback_start" in _OUTPUT_PARAMS:
                # The page reports when the avatar really starts speaking.
                options["wait_playback_start"] = True
            output = DataStreamAudioOutput(
                room,
                destination_identity=identity,
                sample_rate=self._sample_rate,
                **options,  # type: ignore[arg-type]
            )
            agent_session.output.audio = output

            self._visitor_identity = identity
            self._audio_output = output
            self._agent_session = agent_session
            logger.info(
                "MeshLite avatar voice routed to the visitor page",
                extra={"visitor_identity": identity, "sample_rate": self._sample_rate},
            )
        finally:
            self._starting = False

    async def aclose(self) -> None:
        """Stop routing the voice to the avatar.

        Unlike video avatar plugins this never removes a participant from the
        room: the only participant involved is the visitor.
        """
        if self._closed:
            return
        self._closed = True
        session, output = self._agent_session, self._audio_output
        self._agent_session = None
        if session is not None and output is not None and session.output.audio is output:
            session.output.audio = None
