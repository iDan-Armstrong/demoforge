"""ArcGIS Online / Portal token plumbing — stdlib only, no arcgis package.

Three ways in, matching the vault's entry kinds:

* ``generate_token``  — agol-user: username/password against
  ``/sharing/rest/generateToken`` (works on AGO and on-prem Portal).
* ``oauth_token``     — agol-oauth: client-credentials flow against
  ``/sharing/rest/oauth2/token`` for a registered application.
* ``validate_api_key`` — api-key: proves the key answers on
  ``/sharing/rest/portals/self``.

Each returns a small dict and raises :class:`AgoError` with the portal's
own message on failure. Nothing here logs or returns the credential.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_PORTAL = "https://www.arcgis.com"
_TIMEOUT = 20  # seconds


class AgoError(Exception):
    """A portal said no (bad credential, bad URL, network trouble)."""


def _rest(portal: str) -> str:
    portal = (portal or DEFAULT_PORTAL).strip().rstrip("/")
    if not portal.startswith(("https://", "http://")):
        portal = "https://" + portal
    return portal + "/sharing/rest"


def _post(url: str, params: dict) -> dict:
    data = urllib.parse.urlencode({**params, "f": "json"}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AgoError(f"HTTP {exc.code} from {url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AgoError(f"could not reach portal: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AgoError("portal returned a non-JSON response") from exc
    err = doc.get("error")
    if err:
        details = "; ".join(err.get("details") or [])
        msg = err.get("message", "unknown portal error")
        raise AgoError(f"{msg}{' — ' + details if details else ''}")
    return doc


def _get(url: str, params: dict) -> dict:
    return _post(url, params)  # Esri REST accepts POST everywhere GET works


def generate_token(portal: str, username: str, password: str) -> dict:
    """Username/password sign-in. Returns {'token', 'expires', 'user'}."""
    doc = _post(_rest(portal) + "/generateToken", {
        "username": username,
        "password": password,
        "referer": "https://demoforge.local",
        "expiration": 60,
    })
    token = doc.get("token")
    if not token:
        raise AgoError("portal returned no token")
    return {"token": token, "expires": doc.get("expires"),
            "user": _whoami(portal, token)}


def oauth_token(portal: str, client_id: str, client_secret: str) -> dict:
    """App client-credentials flow. Returns {'token', 'expires_in'}."""
    doc = _post(_rest(portal) + "/oauth2/token", {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    })
    token = doc.get("access_token")
    if not token:
        raise AgoError("portal returned no access_token")
    return {"token": token, "expires_in": doc.get("expires_in")}


def validate_api_key(portal: str, api_key: str) -> dict:
    """Prove an API key answers. Returns {'portal_name', 'org_id'}."""
    doc = _get(_rest(portal) + "/portals/self", {"token": api_key})
    return {"portal_name": doc.get("name", ""), "org_id": doc.get("id", "")}


def _whoami(portal: str, token: str) -> dict:
    doc = _get(_rest(portal) + "/portals/self", {"token": token})
    user = doc.get("user") or {}
    return {
        "username": user.get("username", ""),
        "fullName": user.get("fullName", ""),
        "role": user.get("role", ""),
        "portal_name": doc.get("name", ""),
    }


def test_connection(kind: str, portal: str, identity: str, secret: str) -> dict:
    """One entry point for the workbench: route by vault entry kind.

    Returns {'ok': True, 'summary': <one human line>, ...details}.
    """
    if kind == "agol-user":
        info = generate_token(portal, identity, secret)
        u = info["user"]
        who = u.get("fullName") or u.get("username") or identity
        return {"ok": True, "summary": f"signed in as {who} ({u.get('role', '?')}) "
                                       f"on {u.get('portal_name') or portal}"}
    if kind == "agol-oauth":
        info = oauth_token(portal, identity, secret)
        return {"ok": True, "summary": "app token issued "
                                       f"(expires in {info.get('expires_in', '?')}s)"}
    if kind == "api-key":
        info = validate_api_key(portal, secret)
        where = info.get("portal_name") or portal
        return {"ok": True, "summary": f"API key accepted on {where}"}
    raise AgoError(f"unknown credential kind {kind!r}")
