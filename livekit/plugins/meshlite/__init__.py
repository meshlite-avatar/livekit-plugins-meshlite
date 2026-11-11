"""MeshLite avatar plugin for LiveKit Agents.

See https://console.meshlite.io for the web SDK that renders the avatar.
"""

from livekit.agents import Plugin

from .avatar import DEFAULT_SAMPLE_RATE, AvatarSession
from .log import logger
from .version import __version__

__all__ = ["AvatarSession", "DEFAULT_SAMPLE_RATE", "__version__"]


class MeshLitePlugin(Plugin):
    def __init__(self) -> None:
        super().__init__(__name__, __version__, __package__, logger)


Plugin.register_plugin(MeshLitePlugin())
