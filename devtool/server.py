"""demoforge dev harness — a local, zero-dependency web workbench.

    python devtool/server.py          # then open http://localhost:8765

Paste or load a GeoJSON FeatureCollection, set the forge config, and run:
the page shows before/after previews, the stats, and the leak-audit report,
and lets you download the forged GeoJSON. Standard library only, bound to
localhost on purpose — this is a development tool, not a service.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from demoforge.audit import to_markdown  # noqa: E402
from demoforge.fake import FieldPolicy  # noqa: E402
from demoforge.pipeline import forge_geojson  # noqa: E402

HOST, PORT = "127.0.0.1", 8765
HTML_PATH = Path(__file__).with_name("ui.html")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path in ("/", "/index.html"):
            self._send(200, HTML_PATH.read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        if self.path != "/api/forge":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            cfg = payload["config"]
            policies = [
                FieldPolicy(p["field"], p["action"])
                for p in cfg.get("policies", [])
            ]
            result = forge_geojson(
                payload["geojson"],
                seed=cfg["seed"],
                target_bounds=tuple(cfg["target_bounds"]),
                rotation_deg=float(cfg.get("rotation_deg", 0)),
                policies=policies,
                blocklist=cfg.get("blocklist", []),
            )
            body = json.dumps({
                "geojson": result.geojson,
                "stats": result.stats,
                "audit_markdown": to_markdown(result.findings),
                "findings": [f.__dict__ for f in result.findings],
            }).encode()
            self._send(200, body, "application/json")
        except Exception as exc:  # dev tool: surface the error to the page
            self._send(400, json.dumps({"error": str(exc)}).encode(),
                       "application/json")

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("  " + fmt % args + "\n")


def main() -> None:
    server = HTTPServer((HOST, PORT), Handler)
    print(f"demoforge dev harness: http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
