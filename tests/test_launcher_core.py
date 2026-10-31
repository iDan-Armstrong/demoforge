"""Headless tests for the control panel's server management (no tkinter)."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "devtool"))

from launcher_core import WorkbenchServer, find_free_port  # noqa: E402


def test_find_free_port_returns_usable_port():
    port = find_free_port()
    assert 0 < port < 65536


def test_server_lifecycle_and_round_trip():
    lines: list[str] = []
    server = WorkbenchServer(log=lines.append)
    assert not server.running
    url = server.start()
    try:
        assert server.running
        assert url.startswith("http://127.0.0.1:")
        # second start is a no-op returning the same URL
        assert server.start() == url

        page = urllib.request.urlopen(url, timeout=5).read().decode()
        assert "demoforge workbench" in page

        payload = {
            "geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature",
                 "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
                 "properties": {"OWNER": "John Smith"}}]},
            "config": {"seed": "s", "target_bounds": [-77.6, 4.0, -76.8, 4.8],
                       "policies": [{"field": "OWNER", "action": "fake:person"}]},
        }
        req = urllib.request.Request(
            url + "/api/forge", json.dumps(payload).encode(),
            {"Content-Type": "application/json"})
        data = json.loads(urllib.request.urlopen(req, timeout=5).read())
        assert data["stats"]["features"] == 1
        assert data["geojson"]["features"][0]["properties"]["OWNER"] != "John Smith"
    finally:
        server.stop()
    assert not server.running
    assert any("running" in line for line in lines)
