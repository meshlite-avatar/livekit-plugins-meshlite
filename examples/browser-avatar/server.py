"""Example web server: serves the page and creates the two session tokens.

GET  /              the demo page
POST /api/session   LiveKit participant token + MeshLite session token (audio "livekit")

LIVEKIT_API_SECRET and MESHLITE_SECRET_KEY stay on this server; the browser only gets
short-lived tokens. Before going live, authenticate your visitors and rate-limit
/api/session.

Run:  python server.py   then open http://localhost:8080
"""

from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path

import aiohttp
from aiohttp import web
from dotenv import load_dotenv
from livekit import api

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

LIVEKIT_URL = os.environ["LIVEKIT_URL"]
LIVEKIT_API_KEY = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
MESHLITE_API = os.environ.get("MESHLITE_API", "https://console.meshlite.io").rstrip("/")
MESHLITE_PUBLISHABLE_KEY = os.environ["MESHLITE_PUBLISHABLE_KEY"]
MESHLITE_SECRET_KEY = os.environ["MESHLITE_SECRET_KEY"]
MESHLITE_AVATAR = os.environ["MESHLITE_AVATAR"]
MESHLITE_SDK_VERSION = os.environ.get("MESHLITE_SDK_VERSION", "1.11.52")
# The address of this page. It must be declared as a domain in the MeshLite console
# (http://localhost is accepted for test keys only).
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "http://localhost:8080").rstrip("/")
PORT = int(os.environ.get("PORT", "8080"))

NO_STORE = {"Cache-Control": "no-store"}


async def index(_request: web.Request) -> web.Response:
    sdk = f"{MESHLITE_API}/sdk/{MESHLITE_SDK_VERSION}/meshlite.js"
    html = (HERE / "index.html").read_text(encoding="utf-8").replace("__MESHLITE_SDK__", sdk)
    return web.Response(text=html, content_type="text/html", headers=NO_STORE)


async def create_session(_request: web.Request) -> web.Response:
    room = f"meshlite-demo-{secrets.token_hex(4)}"
    identity = f"visitor-{secrets.token_hex(3)}"
    participant_token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name("Visitor")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,  # the page reports playback to the agent
            )
        )
        .with_ttl(timedelta(minutes=15))
        .to_jwt()
    )

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        async with http.post(
            f"{MESHLITE_API}/api/v1/client-sessions",
            headers={"Authorization": f"Bearer {MESHLITE_SECRET_KEY}"},
            json={
                "publishableKey": MESHLITE_PUBLISHABLE_KEY,
                "origin": PUBLIC_ORIGIN,  # set here, never copied from the browser
                "avatar": MESHLITE_AVATAR,
                "audio": "livekit",
            },
        ) as response:
            status = response.status
            try:
                body = await response.json(content_type=None)
            except ValueError:
                body = {}

    if status >= 300 or not isinstance(body, dict) or not body.get("sessionToken"):
        code = (body.get("code") or body.get("error")) if isinstance(body, dict) else None
        return web.json_response(
            {"error": "meshlite_session_refused", "code": str(code or status)}, status=502, headers=NO_STORE
        )

    return web.json_response(
        {
            "livekitUrl": LIVEKIT_URL,
            "participantToken": participant_token,
            "sessionToken": body["sessionToken"],
            "publishableKey": MESHLITE_PUBLISHABLE_KEY,
            "avatar": MESHLITE_AVATAR,
        },
        headers=NO_STORE,
    )


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/api/session", create_session)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="127.0.0.1", port=PORT)
