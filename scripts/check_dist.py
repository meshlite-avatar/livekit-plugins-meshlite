"""Fail unless the built wheel and sdist contain only the plugin files.

Usage: python scripts/check_dist.py dist [--tag v0.1.0]
"""

from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from pathlib import Path

PLUGIN = r"livekit/plugins/meshlite/(__init__\.py|avatar\.py|languages\.py|log\.py|version\.py|py\.typed)"
WHEEL_OK = re.compile(
    rf"^({PLUGIN}|livekit_plugins_meshlite-[^/]+\.dist-info/(METADATA|WHEEL|RECORD|licenses/LICENSE))$"
)
SDIST_OK = re.compile(
    rf"^livekit_plugins_meshlite-[^/]+/({PLUGIN}|README\.md|LICENSE|pyproject\.toml|PKG-INFO|\.gitignore)$"
)
# Anything that looks like a credential must never ship.
SECRET = re.compile(
    rb"ml_(sk|pk)_(live|test)_[A-Za-z0-9]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}"
    rb"|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|pypi-[A-Za-z0-9_-]{20,}"
)


def version() -> str:
    text = Path("livekit/plugins/meshlite/version.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def main() -> int:
    args = sys.argv[1:]
    dist = Path(args[0] if args else "dist")
    tag = args[args.index("--tag") + 1] if "--tag" in args else None
    errors: list[str] = []

    if tag is not None and tag != f"v{version()}":
        errors.append(f"tag {tag} does not match the package version v{version()}")

    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        errors.append(f"expected one wheel and one sdist, found {len(wheels)} and {len(sdists)}")

    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                print(f"wheel  {name}")
                if not WHEEL_OK.match(name):
                    errors.append(f"unexpected file in the wheel: {name}")
                elif SECRET.search(archive.read(name)):
                    errors.append(f"credential-like text in the wheel: {name}")

    for sdist in sdists:
        with tarfile.open(sdist) as archive:
            for member in archive.getmembers():
                if member.isdir():
                    continue
                print(f"sdist  {member.name}")
                if not member.isfile() or not SDIST_OK.match(member.name):
                    errors.append(f"unexpected file in the sdist: {member.name}")
                elif SECRET.search(archive.extractfile(member).read()):
                    errors.append(f"credential-like text in the sdist: {member.name}")

    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    if not errors:
        print("ok: only plugin files, no credential-like text")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
