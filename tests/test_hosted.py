from __future__ import annotations

import io
import json
import urllib.parse

import pytest

from demoforge import ago, hosted
from demoforge.ago import AgoError

LAYER = "https://services.arcgis.com/abc/arcgis/rest/services/Parcels/FeatureServer/0"


def feat(i: int) -> dict:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [i, i]},
            "properties": {"PID": f"P-{i}"}}


class FakeService:
    """Mocked urlopen for a hosted feature layer with paging."""

    def __init__(self, monkeypatch, total: int, max_record_count=3,
                 formats="JSON, geoJSON, PBF"):
        self.total, self.mrc, self.formats = total, max_record_count, formats
        self.queries: list[dict] = []
        monkeypatch.setattr(ago.urllib.request, "urlopen", self)

    def __call__(self, req, timeout=0):
        params = dict(urllib.parse.parse_qsl(req.data.decode()))
        if req.full_url.endswith("/query"):
            self.queries.append(params)
            off = int(params["resultOffset"])
            n = min(int(params["resultRecordCount"]), self.total - off)
            doc = {"type": "FeatureCollection",
                   "features": [feat(i) for i in range(off, off + max(n, 0))]}
        else:
            doc = {"name": "Parcels", "maxRecordCount": self.mrc,
                   "supportedQueryFormats": self.formats}
        return io.BytesIO(json.dumps(doc).encode())


def test_fetch_pages_through_everything(monkeypatch):
    svc = FakeService(monkeypatch, total=7, max_record_count=3)
    pages = []
    name, fc = hosted.fetch_layer_geojson(LAYER + "/", token="TOK",
                                          on_page=pages.append)
    assert name == "Parcels"
    assert [f["properties"]["PID"] for f in fc["features"]] == [
        f"P-{i}" for i in range(7)]
    assert pages == [3, 6, 7]
    # token on every request, offsets advance by the server's page size
    assert all(q["token"] == "TOK" for q in svc.queries)
    assert [q["resultOffset"] for q in svc.queries] == ["0", "3", "6"]
    assert all(q["f"] == "geojson" for q in svc.queries)


def test_exact_page_multiple_terminates(monkeypatch):
    svc = FakeService(monkeypatch, total=6, max_record_count=3)
    _, fc = hosted.fetch_layer_geojson(LAYER)
    assert len(fc["features"]) == 6
    assert len(svc.queries) == 3  # last page comes back empty, then stop


def test_public_layer_needs_no_token(monkeypatch):
    svc = FakeService(monkeypatch, total=2)
    hosted.fetch_layer_geojson(LAYER)
    assert all("token" not in q for q in svc.queries)


def test_no_geojson_support_is_a_clear_error(monkeypatch):
    FakeService(monkeypatch, total=2, formats="JSON, PBF")
    with pytest.raises(AgoError, match="does not offer GeoJSON"):
        hosted.fetch_layer_geojson(LAYER)


def test_page_size_is_capped(monkeypatch):
    svc = FakeService(monkeypatch, total=1, max_record_count=50000)
    hosted.fetch_layer_geojson(LAYER)
    assert int(svc.queries[0]["resultRecordCount"]) == hosted._PAGE_CAP


def test_get_token_routes_by_kind(monkeypatch):
    FakeService(monkeypatch, total=0)  # not used for api-key

    def fake_generate(portal, u, p):
        return {"token": "USERTOK"}

    def fake_oauth(portal, c, s):
        return {"token": "APPTOK"}

    monkeypatch.setattr(ago, "generate_token", fake_generate)
    monkeypatch.setattr(ago, "oauth_token", fake_oauth)
    assert ago.get_token("agol-user", "", "u", "p") == "USERTOK"
    assert ago.get_token("agol-oauth", "", "c", "s") == "APPTOK"
    assert ago.get_token("api-key", "", "", "KEY123") == "KEY123"
    with pytest.raises(AgoError, match="unknown credential kind"):
        ago.get_token("ssh", "", "", "")
