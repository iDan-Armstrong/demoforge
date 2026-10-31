"""GUI-free launcher logic: start/stop the workbench server in-process.

Separated from the tkinter shell so it's testable headless (and reusable
by anything else that wants to embed the workbench). No pip install
required: like server.py, it puts the repo's src/ on sys.path itself.
"""

from __future__ import annotations

import socket
import sys
import threading
from http.server import HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "devtool"))

HOST = "127.0.0.1"
PREFERRED_PORT = 8765


def find_free_port(preferred: int = PREFERRED_PORT) -> int:
    """The preferred port if free, else whatever the OS hands out."""
    for candidate in (preferred, 0):
        try:
            with socket.socket() as s:
                s.bind((HOST, candidate))
                return s.getsockname()[1]
        except OSError:
            continue
    raise OSError("no free port found")


class WorkbenchServer:
    """Owns the HTTP server and its daemon thread."""

    def __init__(self, log=print):
        self._log = log
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int | None = None

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}"

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> str:
        if self.running:
            return self.url
        import server  # devtool/server.py (path injected above)

        self.port = find_free_port()
        handler = server.Handler
        handler.log_message = (  # route request lines to the UI log
            lambda s, fmt, *args: self._log(fmt % args)
        )
        self._server = HTTPServer((HOST, self.port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="workbench"
        )
        self._thread.start()
        self._log(f"workbench running at {self.url}")
        return self.url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._log("workbench stopped")
        self._thread = None
