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
