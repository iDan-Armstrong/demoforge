from __future__ import annotations

import io
import json
import urllib.parse

import pytest

from demoforge import ago
from demoforge.ago import AgoError


class FakePortal:
    """Monkeypatched urlopen: route Esri REST endpoints to canned answers."""

    def __init__(self, monkeypatch, responses: dict[str, dict]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []
        monkeypatch.setattr(ago.urllib.request, "urlopen", self)

    def __call__(self, req, timeout=0):
        url = req.full_url
        params = dict(urllib.parse.parse_qsl(req.data.decode()))
        self.calls.append((url, params))
        for suffix, doc in self.responses.items():
            if url.endswith(suffix):
                return io.BytesIO(json.dumps(doc).encode())
        raise AssertionError(f"unexpected URL {url}")


def test_generate_token_happy_path(monkeypatch):
    portal = FakePortal(monkeypatch, {
        "/generateToken": {"token": "TOK", "expires": 123},
        "/portals/self": {"name": "AWC Org",
                          "user": {"username": "dan", "fullName": "Dan A",
                                   "role": "org_admin"}},
    })
    info = ago.generate_token("https://www.arcgis.com", "dan", "pw")
    assert info["token"] == "TOK"
    assert info["user"]["fullName"] == "Dan A"
    # credential went to the portal, token used for whoami
    assert portal.calls[0][1]["username"] == "dan"
    assert portal.calls[1][1]["token"] == "TOK"


def test_portal_error_is_surfaced(monkeypatch):
    FakePortal(monkeypatch, {
        "/generateToken": {"error": {"code": 400, "message": "Unable to generate token.",
                                     "details": ["Invalid username or password."]}},
    })
    with pytest.raises(AgoError, match="Invalid username or password"):
        ago.generate_token("www.arcgis.com", "dan", "wrong")


def test_oauth_token(monkeypatch):
    FakePortal(monkeypatch, {
        "/oauth2/token": {"access_token": "APPTOK", "expires_in": 7200},
    })
    info = ago.oauth_token("https://www.arcgis.com", "cid", "csecret")
    assert info == {"token": "APPTOK", "expires_in": 7200}


def test_validate_api_key(monkeypatch):
    FakePortal(monkeypatch, {
        "/portals/self": {"name": "AWC Org", "id": "abc123"},
    })
    assert ago.validate_api_key("", "KEY")["portal_name"] == "AWC Org"


def test_rest_url_normalization():
    assert ago._rest("www.arcgis.com/") == "https://www.arcgis.com/sharing/rest"
    assert ago._rest("") == "https://www.arcgis.com/sharing/rest"
    assert (ago._rest("https://gis.example.com/portal")
            == "https://gis.example.com/portal/sharing/rest")


def test_test_connection_routes_by_kind(monkeypatch):
    FakePortal(monkeypatch, {
        "/generateToken": {"token": "T"},
        "/oauth2/token": {"access_token": "A", "expires_in": 60},
        "/portals/self": {"name": "Org", "user": {"username": "dan", "role": "user"}},
    })
    assert "signed in as" in ago.test_connection("agol-user", "", "dan", "pw")["summary"]
    assert "app token" in ago.test_connection("agol-oauth", "", "cid", "cs")["summary"]
    assert "API key accepted" in ago.test_connection("api-key", "", "", "KEY")["summary"]
    with pytest.raises(AgoError, match="unknown credential kind"):
        ago.test_connection("ssh", "", "", "")


def test_network_failure_is_agoerror(monkeypatch):
    def boom(req, timeout=0):
        raise ago.urllib.error.URLError("nope")

    monkeypatch.setattr(ago.urllib.request, "urlopen", boom)
    with pytest.raises(AgoError, match="could not reach portal"):
        ago.validate_api_key("", "KEY")


def test_list_user_items_uses_owner_search(monkeypatch):
    portal = FakePortal(monkeypatch, {
        "/search": {
            "results": [
                {"id": "1", "title": "Parcels", "type": "Feature Service",
                 "url": "https://x/FeatureServer", "owner": "dan"},
                {"id": "2", "title": "A Web Map", "type": "Web Map"},
            ],
            "total": 2, "start": 1, "nextStart": -1},
    })
    items = ago.list_user_items("https://www.arcgis.com", "TOK", "dan")
    titles = {i["title"]: i for i in items}
    assert set(titles) == {"Parcels", "A Web Map"}
    assert titles["Parcels"]["is_layer"] is True
    assert titles["A Web Map"]["is_layer"] is False  # web maps aren't layer-ish
    # a single bulk owner-search, not a per-folder walk
    assert len(portal.calls) == 1
    assert portal.calls[0][1]["q"] == "owner:dan"


def test_list_content_is_paged(monkeypatch):
    portal = FakePortal(monkeypatch, {
        "/portals/self": {"name": "Town Org", "id": "ORG",
                          "user": {"username": "dan"}},
        "/search": {"results": [{"id": "1", "title": "FS", "type": "Feature Service"}],
                    "total": 467, "start": 101, "num": 100, "nextStart": 201},
    })
    out = ago.list_content("https://www.arcgis.com", "TOK",
                           start=101, num=100, layers_only=True)
    assert out["scope"] == "dan's content"
    assert out["total"] == 467 and out["start"] == 101 and out["nextStart"] == 201
    assert out["items"][0]["title"] == "FS"
    # layers_only narrows the query to service types, paged from the right offset
    q = portal.calls[-1][1]
    assert q["start"] == "101" and 'type:"Feature Service"' in q["q"]
    assert "owner:dan" in q["q"]


def test_list_content_unfiltered_has_no_type_clause(monkeypatch):
    portal = FakePortal(monkeypatch, {
        "/portals/self": {"name": "Town Org", "id": "ORG",
                          "user": {"username": "dan"}},
        "/search": {"results": [], "total": 0, "start": 1, "nextStart": -1},
    })
    ago.list_content("https://www.arcgis.com", "TOK")
    assert portal.calls[-1][1]["q"] == "owner:dan"  # no AND (type:...)


def test_list_content_falls_back_to_org_search(monkeypatch):
    portal = FakePortal(monkeypatch, {
        "/portals/self": {"name": "Town Org", "id": "ORG"},  # no user (api-key)
        "/search": {"results": [{"id": "9", "title": "Shared FS",
                                 "type": "Feature Service",
                                 "url": "https://x/FeatureServer"}],
                    "nextStart": -1},
    })
    out = ago.list_content("https://www.arcgis.com", "KEY")
    assert out["scope"] == "organization"
    assert out["items"][0]["title"] == "Shared FS"
    assert any(q.get("q") == "orgid:ORG" for _, q in portal.calls)


def test_list_service_layers_builds_urls(monkeypatch):
    FakePortal(monkeypatch, {
        "/FeatureServer": {
            "layers": [{"id": 0, "name": "Parcels", "geometryType": "esriGeometryPolygon"},
                       {"id": 1, "name": "Pipes", "geometryType": "esriGeometryPolyline"}],
            "tables": [{"id": 2, "name": "Owners"}]},
    })
    layers = ago.list_service_layers("https://x/FeatureServer/", token="TOK")
    assert [lyr["url"] for lyr in layers] == [
        "https://x/FeatureServer/0", "https://x/FeatureServer/1",
        "https://x/FeatureServer/2"]
    assert layers[0]["geometry"] == "Polygon"
    assert layers[2]["kind"] == "table"
