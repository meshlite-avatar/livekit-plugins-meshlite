"""Example LiveKit agent with a MeshLite face.

The agent talks with an OpenAI realtime model, or an Azure OpenAI one (see .env.example;
any STT + LLM + TTS pipeline works the same way). The MeshLite plugin sends its voice to the visitor's page, where the avatar
speaks it with matching lips.

Run:  python run.py   (starts this agent and the web server together)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import meshlite, openai

load_dotenv(Path(__file__).resolve().parent / ".env")

INSTRUCTIONS = """You are a friendly assistant with a face, talking with a visitor of a website.
Keep your answers short and natural: two to four sentences, no long lists."""


def make_model() -> openai.realtime.RealtimeModel:
    """OpenAI by default (OPENAI_API_KEY); Azure OpenAI when AZURE_OPENAI_ENDPOINT is set."""
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    if endpoint:
        # The key is read from AZURE_OPENAI_API_KEY. "azure_deployment" is the name you gave
        # your realtime deployment in the Azure portal.
        return openai.realtime.RealtimeModel.with_azure(
            azure_endpoint=endpoint,
            azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        )
    return openai.realtime.RealtimeModel()


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    session = AgentSession(
        llm=make_model(),
        # The avatar data-stream protocol cannot pause and resume a speech segment.
        resume_false_interruption=False,
    )

    # Route the agent voice to the visitor's page instead of publishing an audio track.
    # Call it after ctx.connect() and before session.start().
    avatar = meshlite.AvatarSession()
    await avatar.start(session, room=ctx.room)

    await session.start(agent=Agent(instructions=INSTRUCTIONS), room=ctx.room)
    session.generate_reply(instructions="Greet the visitor in one short sentence and ask how you can help.")


def no_load(_worker) -> float:
    return 0.0


if __name__ == "__main__":
    # load_fnc=no_load: by default the worker stops accepting visitors when the machine's CPU is
    # busy (70 % in "start" mode), and the browser that draws the avatar runs on this same
    # machine, so the agent would silently refuse the conversation. Remove load_fnc for a
    # production worker on its own server, so that LiveKit can spread visitors between workers.
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, load_fnc=no_load))
