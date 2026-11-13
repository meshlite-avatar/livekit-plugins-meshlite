#!/usr/bin/env python3
"""Run the whole example with one command:  python run.py

Fill in .env first (copy .env.example). Then run.py:

  1. creates a virtual environment in .venv and installs requirements.txt (first run only);
  2. checks .env and tells you what is missing (it never prints a value);
  3. starts the LiveKit agent (agent.py) and the web server (server.py) together,
     with their logs prefixed [agent] and [server];
  4. opens http://localhost:8080 (or the PORT from .env);
  5. stops both cleanly on Ctrl+C.

Only the standard library is used here, so any Python 3.9+ works on Windows, macOS and Linux.

Options:
  --check        only check .env, then exit
  --no-browser   do not open the page
  --no-install   do not touch the virtual environment
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"
ENV_EXAMPLE = HERE / ".env.example"
REQUIREMENTS = HERE / "requirements.txt"
VENV = HERE / ".venv"
IS_WINDOWS = os.name == "nt"

# name -> what to put there (shown when it is missing)
REQUIRED: Dict[str, str] = {
    "LIVEKIT_URL": "address of your LiveKit server: wss://<project>.livekit.cloud, or ws://localhost:7880 with livekit-server --dev",
    "LIVEKIT_API_KEY": "LiveKit API key",
    "LIVEKIT_API_SECRET": "LiveKit API secret",
    "MESHLITE_PUBLISHABLE_KEY": "MeshLite publishable key (Console: Projects, For developers, Keys), starts with ml_pk_",
    "MESHLITE_SECRET_KEY": "MeshLite secret key (Console: Projects, For developers, Keys), starts with ml_sk_",
    "MESHLITE_AVATAR": "avatar id (Console: Projects, For developers, Code)",
}

# The model of the example agent: OpenAI by default, Azure OpenAI when AZURE_OPENAI_ENDPOINT is set
# (the same rule as agent.py).
OPENAI_SETTINGS: Dict[str, str] = {
    "OPENAI_API_KEY": "OpenAI API key used by the example agent (or set the AZURE_OPENAI_* settings to use Azure OpenAI)",
}
AZURE_SETTINGS: Dict[str, str] = {
    "AZURE_OPENAI_API_KEY": "key of your Azure OpenAI resource",
    "AZURE_OPENAI_DEPLOYMENT": "name of your Azure OpenAI realtime deployment (for example gpt-realtime)",
}

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

# Routine agent messages that only add noise to the console.
QUIET_AGENT_MESSAGES = ("initializing job runner", "job runner initialized")


# --------------------------------------------------------------------------------------
# .env reading and checking (no value is ever printed)
# --------------------------------------------------------------------------------------


def read_env_file(path: Path) -> Dict[str, str]:
    """Minimal .env parser: KEY=VALUE, comments, optional export, quotes."""
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, sep, value = line.partition("=")
        name = name.strip()
        if not sep or not name:
            continue
        value = value.strip()
        if value[:1] in ("'", '"') and value.count(value[0]) >= 2:
            quote = value[0]
            value = value[1:value.index(quote, 1)]
        else:
            hash_at = value.find(" #")
            if hash_at >= 0:
                value = value[:hash_at].rstrip()
        values[name] = value
    return values


def is_unset(value: Optional[str]) -> bool:
    """Empty, or still the placeholder from .env.example."""
    if value is None:
        return True
    value = value.strip()
    return (
        not value
        or value.endswith("...")
        or "your-project" in value
        or (value.startswith("<") and value.endswith(">"))
    )


def effective_settings(file_values: Mapping[str, str], environ: Mapping[str, str]) -> Dict[str, str]:
    """Process environment wins over .env, like python-dotenv does in agent.py and server.py."""
    merged: Dict[str, str] = dict(file_values)
    for name, value in environ.items():
        if (name in REQUIRED or name in OPENAI_SETTINGS or name in AZURE_SETTINGS
                or name in ("AZURE_OPENAI_ENDPOINT", "PORT", "PUBLIC_ORIGIN", "MESHLITE_API", "MESHLITE_SDK_VERSION")):
            if value.strip():
                merged[name] = value
    return merged


def validate(settings: Mapping[str, str]) -> Tuple[List[str], List[str]]:
    """Return (problems, warnings). Messages name the setting, never its value."""
    problems: List[str] = []
    warnings: List[str] = []

    for name, hint in REQUIRED.items():
        if is_unset(settings.get(name)):
            problems.append(f"{name} is not set: {hint}")

    endpoint = settings.get("AZURE_OPENAI_ENDPOINT", "")
    if is_unset(endpoint):
        model_settings = OPENAI_SETTINGS
    else:
        model_settings = AZURE_SETTINGS
        if urlparse(endpoint).scheme != "https":
            problems.append("AZURE_OPENAI_ENDPOINT must start with https:// (for example https://my-resource.openai.azure.com)")
    for name, hint in model_settings.items():
        if is_unset(settings.get(name)):
            problems.append(f"{name} is not set: {hint}")

    url = settings.get("LIVEKIT_URL", "")
    if not is_unset(url) and urlparse(url).scheme not in ("ws", "wss", "http", "https"):
        problems.append("LIVEKIT_URL must start with wss:// (or ws:// for a local server)")

    pk = settings.get("MESHLITE_PUBLISHABLE_KEY", "")
    sk = settings.get("MESHLITE_SECRET_KEY", "")
    if not is_unset(pk) and not pk.startswith("ml_pk_"):
        problems.append("MESHLITE_PUBLISHABLE_KEY must start with ml_pk_ (is it the secret key?)")
    if not is_unset(sk) and not sk.startswith("ml_sk_"):
        problems.append("MESHLITE_SECRET_KEY must start with ml_sk_ (is it the publishable key?)")
    if pk.startswith("ml_pk_") and sk.startswith("ml_sk_"):
        pk_env = "live" if pk.startswith("ml_pk_live_") else "test" if pk.startswith("ml_pk_test_") else None
        sk_env = "live" if sk.startswith("ml_sk_live_") else "test" if sk.startswith("ml_sk_test_") else None
        if pk_env and sk_env and pk_env != sk_env:
            problems.append("MESHLITE_PUBLISHABLE_KEY and MESHLITE_SECRET_KEY are from different environments (test vs live)")
        elif pk_env == "live" and settings.get("PUBLIC_ORIGIN", "http://localhost:8080").startswith("http://"):
            warnings.append("live keys need an https:// PUBLIC_ORIGIN declared as a domain in the MeshLite console")

    port = settings.get("PORT", "8080")
    if not (port.isdigit() and 0 < int(port) < 65536):
        problems.append("PORT must be a number between 1 and 65535")

    return problems, warnings


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------

_print_lock = threading.Lock()
_use_color = False
COLORS = {"run": "36", "agent": "35", "server": "32", "livekit": "33"}


def emit(prefix: str, text: str) -> None:
    label = f"[{prefix}]"
    if _use_color and prefix in COLORS:
        label = f"\033[{COLORS[prefix]}m{label}\033[0m"
    with _print_lock:
        print(f"{label} {text}", flush=True)


def say(text: str) -> None:
    emit("run", text)


def setup_console() -> None:
    global _use_color
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    _use_color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if _use_color and IS_WINDOWS:
        os.system("")  # turns on ANSI escape codes in the Windows console


def tidy_agent_line(text: str) -> Optional[str]:
    """The agent logs one JSON object per line: keep the message (and the traceback of an error)."""
    if not text.startswith("{"):
        return text
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if not isinstance(data, dict) or "message" not in data:
        return text
    level = str(data.get("level", "INFO")).upper()
    message = str(data["message"])
    if level == "DEBUG" or message.startswith(QUIET_AGENT_MESSAGES):
        return None
    line = message if level == "INFO" else f"{level} {message}"
    if level in ("ERROR", "CRITICAL") and data.get("exc_info"):
        line += "\n" + str(data["exc_info"])
    return line


def tidy_livekit_line(text: str) -> Optional[str]:
    """livekit-server is chatty: keep warnings and errors, minus a harmless Windows and macOS notice."""
    if ("\tWARN\t" in text or "\tERROR\t" in text) and "CPU monitoring unsupported" not in text:
        return text
    return None


# --------------------------------------------------------------------------------------
# Virtual environment
# --------------------------------------------------------------------------------------


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def run_quiet(command: List[str], what: str) -> None:
    """Run a command, show only its last lines if it fails."""
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(HERE))
    if result.returncode != 0:
        tail = result.stdout.decode("utf-8", errors="replace").strip().splitlines()[-30:]
        for line in tail:
            emit("run", f"  {line}")
        raise SystemExit(f"{what} failed (exit {result.returncode}). See the lines above.")


def ensure_venv(install: bool) -> Path:
    python = venv_python()
    if not install:
        if not python.is_file():
            raise SystemExit(f"No virtual environment at {VENV}. Run without --no-install first.")
        return python

    if not python.is_file():
        say(f"Creating the virtual environment in {VENV} ...")
        run_quiet([sys.executable, "-m", "venv", str(VENV)], "Creating the virtual environment")
        if not python.is_file():
            raise SystemExit(
                f"The virtual environment was not created. On Debian or Ubuntu, install python3-venv first."
            )

    stamp = VENV / ".requirements.sha256"
    wanted = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == wanted:
        return python

    say("Installing the dependencies (first run: one or two minutes) ...")
    run_quiet([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(REQUIREMENTS)],
              "Installing the dependencies")
    stamp.write_text(wanted + "\n", encoding="utf-8")
    say("Dependencies installed.")
    return python


# --------------------------------------------------------------------------------------
# Processes
# --------------------------------------------------------------------------------------


class Child:
    def __init__(self, name: str, command: List[str], env: Mapping[str, str],
                 tidy: Optional[Callable[[str], Optional[str]]] = None) -> None:
        self.name = name
        self.tidy = tidy
        self.quiet = False  # set while stopping: the other programs complain when their peer goes away
        kwargs = {}
        if IS_WINDOWS:
            # Own process group: Ctrl+C in this console only reaches run.py, which stops the children itself.
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(
            command,
            cwd=str(HERE),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        self.lines: List[str] = []
        self.registered = threading.Event()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for raw in iter(self.proc.stdout.readline, b""):
            text = raw.decode("utf-8", errors="replace").rstrip()
            if not text:
                continue
            if "registered worker" in text:
                self.registered.set()
            shown = self.tidy(text) if self.tidy else text
            if shown is None or self.quiet:
                continue
            for line in shown.splitlines():
                emit(self.name, line)
        self.proc.stdout.close()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self, grace: float = 6.0) -> None:
        if not self.alive():
            return
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self._signal_group(signal.SIGINT)
            if not self._wait(grace):
                self._signal_group(signal.SIGTERM)
                if not self._wait(3.0):
                    self._signal_group(signal.SIGKILL)
        self._wait(3.0)

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(self.proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def _wait(self, seconds: float) -> bool:
        try:
            self.proc.wait(timeout=seconds)
            return True
        except subprocess.TimeoutExpired:
            return False


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_for_page(url: str, children: List[Child], timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not all(child.alive() for child in children):
            return False
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.4)
    return False


def maybe_start_local_livekit(settings: Mapping[str, str], env: Mapping[str, str]) -> Optional[Child]:
    """With a local LIVEKIT_URL and nothing listening, start `livekit-server --dev` if it is installed."""
    parsed = urlparse(settings["LIVEKIT_URL"])
    host = parsed.hostname or ""
    if host not in LOCAL_HOSTS:
        return None
    port = parsed.port or 7880
    if port_open("127.0.0.1", port) or port_open(host, port):
        return None
    binary = shutil.which("livekit-server")
    dev_keys = settings.get("LIVEKIT_API_KEY") == "devkey" and settings.get("LIVEKIT_API_SECRET") == "secret"
    if not binary or not dev_keys or port != 7880:
        raise SystemExit(
            f"Nothing is listening at {host}:{port} (LIVEKIT_URL).\n"
            "Start your LiveKit server, or install livekit-server and use "
            "LIVEKIT_URL=ws://localhost:7880 with LIVEKIT_API_KEY=devkey and LIVEKIT_API_SECRET=secret: "
            "run.py then starts it for you."
        )
    say("Starting livekit-server --dev (local LiveKit server).")
    child = Child("livekit", [binary, "--dev", "--bind", "127.0.0.1"], env, tidy=tidy_livekit_line)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if port_open("127.0.0.1", port):
            return child
        if not child.alive():
            raise SystemExit("livekit-server stopped right after it started. See the [livekit] lines above.")
        time.sleep(0.3)
    child.stop()
    raise SystemExit("livekit-server did not open its port in 30 seconds.")


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MeshLite + LiveKit example with one command.")
    parser.add_argument("--check", action="store_true", help="only check .env, then exit")
    parser.add_argument("--no-browser", action="store_true", help="do not open the page")
    parser.add_argument("--no-install", action="store_true", help="do not create or update the virtual environment")
    return parser.parse_args(argv)


def check_env() -> Dict[str, str]:
    if not ENV_FILE.is_file():
        if ENV_EXAMPLE.is_file():
            shutil.copyfile(ENV_EXAMPLE, ENV_FILE)
            say(f"Created {ENV_FILE} from .env.example.")
        else:
            raise SystemExit(f"{ENV_FILE} is missing. Create it from the README.")
    settings = effective_settings(read_env_file(ENV_FILE), os.environ)
    problems, warnings = validate(settings)
    for warning in warnings:
        say(f"Note: {warning}")
    if problems:
        say(f"Fill in {ENV_FILE}, then run this command again:")
        for problem in problems:
            say(f"  - {problem}")
        raise SystemExit(1)
    return settings


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    setup_console()

    if sys.version_info < (3, 9):
        raise SystemExit("Python 3.9 or later is required.")

    settings = check_env()
    if args.check:
        say("Configuration looks complete.")
        return 0

    port = int(settings.get("PORT", "8080"))
    if port_open("127.0.0.1", port):
        raise SystemExit(f"Port {port} is already in use. Stop the other program or change PORT in .env.")

    python = ensure_venv(install=not args.no_install)

    env = dict(os.environ)
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    env.pop("PYTHONHOME", None)
    if settings.get("LIVEKIT_API_SECRET") == "secret":
        # The local LiveKit dev key is 6 bytes long: PyJWT warns about it on every token. Expected here.
        env["PYTHONWARNINGS"] = "ignore:The HMAC key is:Warning"

    children: List[Child] = []

    def shutdown(_signum: Optional[int] = None, _frame: object = None) -> None:
        raise KeyboardInterrupt

    if not IS_WINDOWS:
        signal.signal(signal.SIGTERM, shutdown)

    exit_code = 0
    try:
        livekit = maybe_start_local_livekit(settings, env)
        if livekit:
            children.append(livekit)

        agent = Child("agent", [str(python), "agent.py", "start"], env, tidy=tidy_agent_line)
        children.append(agent)
        server = Child("server", [str(python), "server.py"], env)
        children.append(server)

        url = f"http://localhost:{port}"
        if not wait_for_page(f"http://127.0.0.1:{port}/", children):
            for child in children:
                if not child.alive():
                    say(f"{child.name} stopped (exit {child.proc.returncode}). See the [{child.name}] lines above.")
                    return 2
            say("The page did not answer within 60 seconds. See the [server] lines above.")
            return 2

        # A visitor who presses Start before the agent has registered would find nobody to talk to:
        # open the page only once the agent is connected to LiveKit.
        say("Waiting for the agent to connect to LiveKit ...")
        deadline = time.monotonic() + 90
        while not agent.registered.is_set() and time.monotonic() < deadline:
            for child in children:
                if not child.alive():
                    say(f"{child.name} stopped (exit {child.proc.returncode}). See the [{child.name}] lines above.")
                    return 2
            time.sleep(0.3)
        if agent.registered.is_set():
            say("The agent is connected to LiveKit and waits for a visitor.")
        else:
            say("Note: the agent has not reported a connection to LiveKit yet. Check the [agent] lines.")

        say("")
        say(f"Ready: {url}")
        say("Press Start in the page and allow the microphone. Press Ctrl+C here to stop everything.")
        say("")
        if not args.no_browser:
            webbrowser.open(url)

        while True:
            for child in children:
                if not child.alive():
                    say(f"{child.name} stopped (exit {child.proc.returncode}). Stopping the rest.")
                    exit_code = 2
                    return exit_code
            time.sleep(0.3)
    except KeyboardInterrupt:
        for child in children:
            child.quiet = True
        say("Stopping ...")
        return 0
    finally:
        for child in reversed(children):
            child.stop()
        if children:
            say("Stopped.")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:  # Ctrl+C while the virtual environment is being prepared
        print("\nInterrupted.", flush=True)
        sys.exit(130)
