"""Example LiveKit agent with a MeshLite face.

The agent talks with an OpenAI realtime model (any STT + LLM + TTS pipeline works the
same way). The MeshLite plugin sends its voice to the visitor's page, where the avatar
speaks it with matching lips.

Run:  python agent.py dev
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import meshlite, openai

load_dotenv(Path(__file__).resolve().parent / ".env")

INSTRUCTIONS = """You are a friendly assistant with a face, talking with a visitor of a website.
Keep your answers short and natural: two to four sentences, no long lists."""


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    session = AgentSession(
        llm=openai.realtime.RealtimeModel(),
        # The avatar data-stream protocol cannot pause and resume a speech segment.
        resume_false_interruption=False,
    )

    # Route the agent voice to the visitor's page instead of publishing an audio track.
    # Call it after ctx.connect() and before session.start().
    avatar = meshlite.AvatarSession()
    await avatar.start(session, room=ctx.room)

    await session.start(agent=Agent(instructions=INSTRUCTIONS), room=ctx.room)
    session.generate_reply(instructions="Greet the visitor in one short sentence and ask how you can help.")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
