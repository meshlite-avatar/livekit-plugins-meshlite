"""Example server: the page, the MeshLite session token and the Pipecat bot, in one process.

GET   /             the demo page (index.html, with the MeshLite SDK filled in)
POST  /api/session  MeshLite session token for this page (audio "track")
POST  /api/offer    WebRTC offer from the page: starts one Pipecat bot for this visitor
PATCH /api/offer    WebRTC ICE candidates
GET   /health       "ok" while the server runs

The bot: visitor microphone -> OpenAI Realtime (or Azure OpenAI Realtime) -> voice track
back to the page. The page hands that track to the MeshLite face (avatar.attachPipecat):
nothing MeshLite-specific runs here, apart from creating the session token.

MESHLITE_SECRET_KEY and the model key stay on this server; the browser only gets a
short-lived session token. Before going live, authenticate your visitors and rate-limit
/api/session and /api/offer.

Run:  python bot.py   then open http://localhost:8080   (python run.py does everything)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from loguru import logger

# Short, uncoloured logs (set before Pipecat is imported, which logs at import time).
logger.remove()
logger.add(sys.stderr, level=os.environ.get("LOG_LEVEL", "INFO"), format="{level: <7} {message}", colorize=False)

from pipecat.frames.frames import LLMRunFrame  # noqa: E402
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

MESHLITE_API = os.environ.get("MESHLITE_API", "https://console.meshlite.io").rstrip("/")
MESHLITE_PUBLISHABLE_KEY = os.environ["MESHLITE_PUBLISHABLE_KEY"]
MESHLITE_SECRET_KEY = os.environ["MESHLITE_SECRET_KEY"]
MESHLITE_AVATAR = os.environ["MESHLITE_AVATAR"]
MESHLITE_SDK_VERSION = os.environ.get("MESHLITE_SDK_VERSION", "1.11.52")
# The address of this page. It must be declared as a site in the MeshLite console
# (http://localhost is accepted for test keys only).
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "http://localhost:8080").rstrip("/")
PORT = int(os.environ.get("PORT", "8080"))

SAMPLE_RATE = 24000  # the realtime models speak 24 kHz PCM: keep it end to end
INSTRUCTIONS = os.environ.get("BOT_INSTRUCTIONS") or (
    "You are a friendly assistant with a face, talking with a visitor by voice. "
    "Answer in the visitor's language, in one to three short sentences, unless they ask "
    "for something longer. If they interrupt you, stop and listen."
)
GREETING = "Greet the visitor in one short sentence and ask how you can help."

NO_STORE = {"Cache-Control": "no-store"}


def make_llm():
    """OpenAI Realtime by default, Azure OpenAI Realtime when AZURE_OPENAI_ENDPOINT is set."""
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    if endpoint:
        from pipecat.services.azure.realtime.llm import AzureRealtimeLLMService

        host = endpoint.split("://", 1)[-1].split("/", 1)[0]
        return AzureRealtimeLLMService(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            base_url=f"wss://{host}/openai/v1/realtime",
            settings=AzureRealtimeLLMService.Settings(
                model=os.environ["AZURE_OPENAI_DEPLOYMENT"],  # the deployment name
                system_instruction=INSTRUCTIONS,
            ),
        )

    from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService

    settings = {"system_instruction": INSTRUCTIONS}
    if os.environ.get("OPENAI_REALTIME_MODEL", "").strip():
        settings["model"] = os.environ["OPENAI_REALTIME_MODEL"].strip()
    return OpenAIRealtimeLLMService(
        api_key=os.environ["OPENAI_API_KEY"],
        settings=OpenAIRealtimeLLMService.Settings(**settings),
    )


async def run_bot(connection) -> None:
    """One bot per visitor. The realtime model hears the visitor, answers by voice and
    detects interruptions itself (server VAD); Pipecat sends the voice and the RTVI events
    (botStartedSpeaking, botInterrupted, ...) to the page, where the avatar uses them."""
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True, audio_out_sample_rate=SAMPLE_RATE),
    )
    llm = make_llm()
    context = LLMContext([{"role": "user", "content": GREETING}])
    aggregators = LLMContextAggregatorPair(context)
    pipeline = Pipeline([transport.input(), aggregators.user(), llm, transport.output(), aggregators.assistant()])
    worker = PipelineWorker(
        pipeline, params=PipelineParams(audio_in_sample_rate=SAMPLE_RATE, audio_out_sample_rate=SAMPLE_RATE)
    )

    @worker.rtvi.event_handler("on_client_ready")
    async def on_client_ready(_rtvi):
        logger.info("Visitor connected: the bot greets them.")
        await worker.queue_frames([LLMRunFrame()])  # the bot speaks first

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _client):
        logger.info("Visitor left.")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


async def create_meshlite_session() -> JSONResponse:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        async with http.post(
            f"{MESHLITE_API}/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {MESHLITE_SECRET_KEY}"},
            json={
                "publishableKey": MESHLITE_PUBLISHABLE_KEY,
                "origin": PUBLIC_ORIGIN,  # set here, never copied from the browser
                "avatar": MESHLITE_AVATAR,
                "audio": "track",  # the face follows an audio track the page already receives
            },
        ) as response:
            status = response.status
            try:
                body = await response.json(content_type=None)
            except ValueError:
                body = {}

    if status >= 300 or not isinstance(body, dict) or not body.get("sessionToken"):
        code = (body.get("code") or body.get("error")) if isinstance(body, dict) else None
        logger.warning(f"MeshLite refused the session: {code or status}")
        return JSONResponse(
            {"error": "meshlite_session_refused", "code": str(code or status)}, status_code=502, headers=NO_STORE
        )
    return JSONResponse(
        {"sessionToken": body["sessionToken"], "publishableKey": MESHLITE_PUBLISHABLE_KEY, "avatar": MESHLITE_AVATAR},
        headers=NO_STORE,
    )


def make_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    webrtc = SmallWebRTCRequestHandler()

    @app.get("/")
    async def index():
        sdk = f"{MESHLITE_API}/sdk/{MESHLITE_SDK_VERSION}/meshlite.js"
        html = (HERE / "index.html").read_text(encoding="utf-8").replace("__MESHLITE_SDK__", sdk)
        return HTMLResponse(html, headers=NO_STORE)

    @app.get("/health")
    async def health():
        return PlainTextResponse("ok", headers=NO_STORE)

    @app.post("/api/session")
    async def session():
        return await create_meshlite_session()

    @app.post("/api/offer")
    async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks):
        async def start(connection):
            background_tasks.add_task(run_bot, connection)

        return await webrtc.handle_web_request(request=request, webrtc_connection_callback=start)

    @app.patch("/api/offer")
    async def ice_candidates(request: SmallWebRTCPatchRequest):
        await webrtc.handle_patch_request(request)
        return {"status": "success"}

    return app


if __name__ == "__main__":
    uvicorn.run(make_app(), host="127.0.0.1", port=PORT, log_level="warning")
