"""MeshLite avatar plugin for LiveKit Agents.

See https://console.meshlite.io for the web SDK that renders the avatar.
"""

from livekit.agents import Plugin

from .avatar import DEFAULT_SAMPLE_RATE, SET_LANGUAGE_RPC, AvatarSession
from .languages import MESHLITE_LANGUAGES, spoken_language_of
from .log import logger
from .version import __version__

__all__ = [
    "DEFAULT_SAMPLE_RATE",
    "MESHLITE_LANGUAGES",
    "SET_LANGUAGE_RPC",
    "AvatarSession",
    "__version__",
    "spoken_language_of",
]


class MeshLitePlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)


Plugin.register_plugin(MeshLitePlugin())
