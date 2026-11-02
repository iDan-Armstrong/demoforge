"""demoforge dev harness — a local, zero-dependency web workbench.

    python devtool/server.py          # then open http://localhost:8765

Menu: Workbench (forge GeoJSON, see previews and the leak audit) and
Connections (ArcGIS Online credentials in the local vault — DPAPI-encrypted
on Windows, OS keyring elsewhere).

Standard library only, bound to localhost on purpose. Because the server
can now reach stored secrets, every mutating request must carry the
``X-Demoforge: 1`` header: a cross-site page can't add that header without
a CORS preflight this server never grants, so drive-by POSTs from the
browser are rejected even on localhost.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from demoforge import ago  # noqa: E402
from demoforge.audit import to_markdown  # noqa: E402
from demoforge.fake import FieldPolicy  # noqa: E402
from demoforge.pipeline import forge_geojson  # noqa: E402
from demoforge.vault import Vault, VaultError, default_backend  # noqa: E402

HOST, PORT = "127.0.0.1", 8765
HTML_PATH = Path(__file__).with_name("ui.html")


def open_vault() -> Vault:
    return Vault()  # default path + platform backend


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, doc: dict) -> None:
        self._send(code, json.dumps(doc).encode(), "application/json")

    def _guarded_payload(self) -> dict | None:
        """CSRF guard + body parse; answers the request itself on failure."""
        if self.headers.get("X-Demoforge") != "1":
            self._json(403, {"error": "missing X-Demoforge header"})
            return None
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            self._json(400, {"error": "body is not valid JSON"})
            return None

    # -- GET ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path in ("/", "/index.html"):
            self._send(200, HTML_PATH.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/vault":
            self._vault_status()
        else:
            self._send(404, b"not found", "text/plain")

    def _vault_status(self) -> None:
        try:
            backend = default_backend()
        except VaultError as exc:
            self._json(200, {"available": False, "reason": str(exc), "entries": []})
            return
        try:
            entries = open_vault().list()
        except VaultError as exc:
            self._json(200, {"available": False, "reason": str(exc), "entries": []})
            return
        self._json(200, {"available": True, "backend": backend.name,
                         "entries": entries})

    # -- POST -----------------------------------------------------------

    ROUTES = {
        "/api/forge": "_forge",
        "/api/vault": "_vault_set",
        "/api/vault/delete": "_vault_delete",
        "/api/vault/test": "_vault_test",
        "/api/vault/content": "_vault_content",
        "/api/vault/layers": "_vault_layers",
    }

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        route = self.ROUTES.get(self.path)
        if route is None:
            self._send(404, b"not found", "text/plain")
            return
        payload = self._guarded_payload()
        if payload is None:
            return
        try:
            getattr(self, route)(payload)
        except (VaultError, ago.AgoError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # dev tool: surface the error to the page
            self._json(400, {"error": f"{type(exc).__name__}: {exc}"})

    def _forge(self, payload: dict) -> None:
        cfg = payload["config"]
        policies = [FieldPolicy(p["field"], p["action"])
                    for p in cfg.get("policies", [])]
        result = forge_geojson(
            payload["geojson"],
            seed=cfg["seed"],
            target_bounds=tuple(cfg["target_bounds"]),
            rotation_deg=float(cfg.get("rotation_deg", 0)),
            policies=policies,
            blocklist=cfg.get("blocklist", []),
        )
        self._json(200, {
            "geojson": result.geojson,
            "stats": result.stats,
            "audit_markdown": to_markdown(result.findings),
            "findings": [f.__dict__ for f in result.findings],
        })

    def _vault_set(self, payload: dict) -> None:
        secret = payload.get("secret")
        entry = open_vault().set(
            payload["name"],
            kind=payload["kind"],
            secret=secret if secret else None,  # blank means keep existing
            portal=payload.get("portal") or "https://www.arcgis.com",
            username=payload.get("username", ""),
        )
        self._json(200, {"saved": True, "entry": entry})

    def _vault_delete(self, payload: dict) -> None:
        open_vault().delete(payload["name"])
        self._json(200, {"deleted": True})

    def _vault_test(self, payload: dict) -> None:
        vault = open_vault()
        meta = vault.get_entry(payload["name"])
        identity = meta["username"]
        secret = vault.get_secret(payload["name"])
        result = ago.test_connection(meta["kind"], meta["portal"],
                                     identity, secret)
        self._json(200, result)

    def _token_for(self, name: str):
        vault = open_vault()
        meta = vault.get_entry(name)
        token = ago.get_token(meta["kind"], meta["portal"],
                              meta["username"], vault.get_secret(name))
        return meta, token

    def _vault_content(self, payload: dict) -> None:
        meta, token = self._token_for(payload["name"])
        result = ago.list_content(meta["portal"], token)
        self._json(200, result)

    def _vault_layers(self, payload: dict) -> None:
        _meta, token = self._token_for(payload["name"])
        layers = ago.list_service_layers(payload["url"], token)
        self._json(200, {"service_url": payload["url"].rstrip("/"),
                         "layers": layers})

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("  " + fmt % args + "\n")


class WorkbenchServer(HTTPServer):
    # fail loudly if another workbench is already on the port, instead of
    # two servers silently racing (Windows lets reused sockets double-bind)
    allow_reuse_address = False


def main() -> None:
    try:
        server = WorkbenchServer((HOST, PORT), Handler)
    except OSError:
        print(f"port {PORT} is busy: another demoforge workbench is already running.")
        print("Close the other demoforge window, then start this one again.")
        sys.exit(1)
    print(f"demoforge dev harness: http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
