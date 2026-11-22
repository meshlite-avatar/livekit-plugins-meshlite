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

MeshLite addition: after each agent reply whose language is clear, RPC
``meshlite.set_language`` (``{"language": "en" | "fr" | "zh-CN"}``) so the page
loads the lip model of the language the agent really speaks. The web SDK
(1.11.62 and later) answers it inside ``attachLiveKit(room)``; older pages
answer "unsupported method" and keep their language.
"""

from __future__ import annotations

import asyncio
import inspect
import json

from livekit import rtc
from livekit.agents import AgentSession, utils
from livekit.agents.voice.avatar import DataStreamAudioOutput

from .languages import MESHLITE_LANGUAGES, spoken_language_of
from .log import logger

DEFAULT_SAMPLE_RATE = 24000
_MIN_SAMPLE_RATE = 8000
_MAX_SAMPLE_RATE = 48000
SET_LANGUAGE_RPC = "meshlite.set_language"
_SET_LANGUAGE_TIMEOUT = 5.0

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
        follow_language: after each reply, tell the page the language the
            agent spoke (English, French or Mandarin Chinese, when it is
            clear) so the lips follow a conversation that changes language.
            The new lip model takes over from the next reply.
    """

    def __init__(
        self,
        *,
        visitor_identity: str | None = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        clear_buffer_timeout: float | None = 2.0,
        follow_language: bool = True,
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
        self._follow_language = bool(follow_language)
        self._language: str | None = None
        self._language_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._room: rtc.Room | None = None

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
            self._room = room
            if self._follow_language:
                agent_session.on("conversation_item_added", self._on_conversation_item)
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
        if session is not None and self._follow_language:
            try:
                session.off("conversation_item_added", self._on_conversation_item)
            except (KeyError, ValueError):
                pass
        for task in list(self._tasks):
            task.cancel()
        if session is not None and output is not None and session.output.audio is output:
            session.output.audio = None

    @property
    def language(self) -> str | None:
        """Last language the page accepted (``None`` until one was sent)."""
        return self._language

    async def set_language(self, language: str) -> bool:
        """Ask the page to load the lip model of ``language``.

        Use it when your agent switches language on its own terms; with
        ``follow_language=True`` the plugin already does it after each reply.

        Args:
            language: ``"en"``, ``"fr"`` or ``"zh-CN"``.

        Returns:
            ``True`` when the page applied it, ``False`` when the page could
            not (older SDK, page not attached yet, unknown language there).
        """
        if language not in MESHLITE_LANGUAGES:
            raise ValueError(f"language must be one of {', '.join(MESHLITE_LANGUAGES)}")
        room, identity = self._room, self._visitor_identity
        if self._closed or room is None or identity is None:
            raise RuntimeError("start the MeshLite AvatarSession before setting its language")
        async with self._language_lock:
            if language == self._language:
                return True
            try:
                await room.local_participant.perform_rpc(
                    destination_identity=identity,
                    method=SET_LANGUAGE_RPC,
                    payload=json.dumps({"language": language}),
                    response_timeout=_SET_LANGUAGE_TIMEOUT,
                )
            except rtc.RpcError as error:
                if error.code == rtc.RpcError.ErrorCode.UNSUPPORTED_METHOD:
                    logger.info(
                        "the visitor page does not follow the agent language yet "
                        "(MeshLite web SDK 1.11.62 or later, attachLiveKit(room))",
                        extra={"language": language},
                    )
                else:
                    logger.warning(
                        "the visitor page did not change the avatar language",
                        extra={"language": language, "error": error.message},
                    )
                return False
            self._language = language
            logger.debug("avatar language changed", extra={"language": language})
            return True

    def _on_conversation_item(self, event: object) -> None:
        item = getattr(event, "item", None)
        if getattr(item, "role", None) != "assistant":
            return
        text = getattr(item, "text_content", None)
        language = spoken_language_of(text) if isinstance(text, str) else None
        if language is None or language == self._language or self._closed:
            return
        task = asyncio.ensure_future(self._follow(language))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _follow(self, language: str) -> None:
        try:
            await self.set_language(language)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never break the agent for a lip model
            logger.exception("could not send the avatar language")
