"""demoforge dev harness — a local, zero-dependency web workbench.

    python devtool/server.py            # then open http://localhost:8765
    python devtool/server.py --reload   # auto-restart + auto-refresh on change

Menu: Workbench (forge GeoJSON, see previews and the leak audit) and
Connections (ArcGIS Online credentials in the local vault — DPAPI-encrypted
on Windows, OS keyring elsewhere).

Standard library only, bound to localhost on purpose. Because the server
can now reach stored secrets, every mutating request must carry the
``X-Demoforge: 1`` header: a cross-site page can't add that header without
a CORS preflight this server never grants, so drive-by POSTs from the
browser are rejected even on localhost.

--reload runs a tiny supervisor that re-launches the server whenever a
source file changes (a local edit, or a ``git pull`` while it runs), and
the page polls ``/api/alive`` so it reloads itself when the server comes
back — no manual restart or hard-refresh.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from demoforge import ago, hosted  # noqa: E402
from demoforge.audit import to_markdown  # noqa: E402
from demoforge.fake import FieldPolicy  # noqa: E402
from demoforge.pipeline import forge_geojson  # noqa: E402
from demoforge.staging import suggest_policy  # noqa: E402
from demoforge.vault import Vault, VaultError, default_backend  # noqa: E402

HOST, PORT = "127.0.0.1", 8765
HTML_PATH = Path(__file__).with_name("ui.html")
_REPO = Path(__file__).resolve().parents[1]
BOOT = 0.0  # epoch when this server process started serving; the page watches it


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
        elif self.path == "/api/alive":
            self._json(200, {"boot": BOOT})  # the page reloads when this changes
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
        "/api/vault/fetch": "_vault_fetch",
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
        result = ago.list_content(
            meta["portal"], token,
            start=int(payload.get("start", 1)),
            num=int(payload.get("num", 100)),
            layers_only=bool(payload.get("layers_only", False)),
            text=payload.get("text", ""),
        )
        self._json(200, result)

    def _vault_layers(self, payload: dict) -> None:
        _meta, token = self._token_for(payload["name"])
        layers = ago.list_service_layers(payload["url"], token)
        self._json(200, {"service_url": payload["url"].rstrip("/"),
                         "layers": layers})

    def _vault_fetch(self, payload: dict) -> None:
        # pull a hosted layer straight into the workbench — no ArcGIS Pro.
        _meta, token = self._token_for(payload["name"])
        name, fc = hosted.fetch_layer_geojson(payload["url"], token)
        fields = sorted({k for feat in fc["features"]
                         for k in (feat.get("properties") or {})})
        self._json(200, {
            "name": name,
            "feature_count": len(fc["features"]),
            "geojson": fc,
            "policies": [suggest_policy(f) for f in fields],
        })

    def log_message(self, fmt: str, *args) -> None:
        msg = fmt % args
        if "/api/alive" in msg:  # the reload poll would spam the console
            return
        sys.stderr.write("  " + msg + "\n")


class WorkbenchServer(HTTPServer):
    # fail loudly if another workbench is already on the port, instead of
    # two servers silently racing (Windows lets reused sockets double-bind)
    allow_reuse_address = False


# --------------------------------------------------------------------------
# Running: plain, a reload supervisor, or the supervised child
# --------------------------------------------------------------------------

_WATCH_GLOBS = ("src/demoforge/*.py", "devtool/*.py", "devtool/ui.html")


def _source_mtime() -> float:
    latest = 0.0
    for pattern in _WATCH_GLOBS:
        for path in _REPO.glob(pattern):
            with contextlib.suppress(OSError):
                latest = max(latest, path.stat().st_mtime)
    return latest


def _bind(*, child: bool) -> WorkbenchServer | None:
    # A supervised child reuses the address so a restart rebinds instantly
    # (the old child is already fully dead by then). A plain start keeps
    # reuse off and fails fast, so an accidental double-run is caught.
    WorkbenchServer.allow_reuse_address = child
    attempts = 20 if child else 1
    for i in range(attempts):
        try:
            return WorkbenchServer((HOST, PORT), Handler)
        except OSError:
            if i + 1 < attempts:
                time.sleep(0.25)
    return None


def _serve(*, child: bool) -> None:
    global BOOT
    server = _bind(child=child)
    if server is None:
        print(f"port {PORT} is busy: another demoforge workbench is already running.")
        print("Close the other demoforge window, then start this one again.")
        sys.exit(1)
    BOOT = time.time()
    print("  server ready" if child
          else f"demoforge dev harness: http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if not child:
            print("\nbye")


def _supervise() -> None:
    print(f"demoforge dev harness (auto-reload): http://{HOST}:{PORT}  (Ctrl+C to stop)")
    child = None
    try:
        while True:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                      "--serve"])
            last = _source_mtime()
            while True:
                time.sleep(1.0)
                if child.poll() is not None:  # child exited (e.g. port busy)
                    print("  server stopped; exiting reload supervisor")
                    return
                if _source_mtime() != last:
                    print("  source changed — restarting server")
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                    break
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        if child and child.poll() is None:
            child.terminate()


def main() -> None:
    args = set(sys.argv[1:])
    if "--reload" in args:
        _supervise()
    else:
        _serve(child="--serve" in args)


if __name__ == "__main__":
    main()
