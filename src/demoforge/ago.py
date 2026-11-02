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
import re
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
    data = urllib.parse.urlencode({"f": "json", **params}).encode()
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


def get_token(kind: str, portal: str, identity: str, secret: str) -> str:
    """Turn any vault entry kind into a usable token string."""
    if kind == "agol-user":
        return generate_token(portal, identity, secret)["token"]
    if kind == "agol-oauth":
        return oauth_token(portal, identity, secret)["token"]
    if kind == "api-key":
        return secret  # an API key is sent as the token directly
    raise AgoError(f"unknown credential kind {kind!r}")


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


# --------------------------------------------------------------------------
# Content browsing — what a connection can reach
# --------------------------------------------------------------------------

# the item types worth staging; others (web maps, apps, notebooks) are noise
# for an extraction workflow, so the dashboard flags these as "layer-ish".
LAYER_TYPES = frozenset({
    "Feature Service", "Map Service", "Feature Collection",
    "Vector Tile Service", "Image Service", "WFS", "Table",
})


def _norm_item(it: dict) -> dict:
    return {
        "id": it.get("id", ""),
        "title": it.get("title") or it.get("name") or "(untitled)",
        "type": it.get("type") or "",
        "url": it.get("url") or "",
        "owner": it.get("owner") or "",
        "is_layer": (it.get("type") or "") in LAYER_TYPES,
    }


# the service types a "layer services only" filter keeps — used both to flag
# items and to narrow the server-side search query.
SERVICE_TYPES = ("Feature Service", "Map Service", "Image Service",
                 "Vector Tile Service", "WFS", "Feature Collection")


def _search_page(portal: str, token: str, query: str,
                 start: int = 1, num: int = 100) -> dict:
    """One page of /search. Returns items + the paging cursor the UI needs."""
    doc = _get(_rest(portal) + "/search", {
        "token": token, "q": query, "num": min(num, 100),
        "start": max(start, 1), "sortField": "title",
    })
    return {
        "items": [_norm_item(it) for it in doc.get("results", [])],
        "total": doc.get("total", 0),
        "start": doc.get("start", start),
        "num": doc.get("num", num),
        "nextStart": doc.get("nextStart", -1),
    }


def list_user_items(portal: str, token: str, username: str) -> list[dict]:
    """All of the user's items (first page) — kept for callers that want a list."""
    return _search_page(portal, token, f"owner:{username}")["items"]


def search_items(portal: str, token: str, orgid: str) -> list[dict]:
    return _search_page(portal, token, f"orgid:{orgid}")["items"]


def _search_terms(text: str) -> list[str]:
    """User search text → safe title-prefix tokens (no AGO query injection)."""
    cleaned = re.sub(r"[^0-9A-Za-z _-]+", " ", text or "")
    return [t for t in cleaned.split() if t]


def list_content(portal: str, token: str, start: int = 1, num: int = 100,
                 layers_only: bool = False, text: str = "") -> dict:
    """One page of everything this connection can reach.

    Routes by whether the token has a user (owner search) or not (org
    search), optionally narrowing to layer-bearing service types and/or a
    title search. Returns
    {'scope', 'portal_name', 'total', 'start', 'num', 'nextStart', 'items'}.
    """
    self_doc = _get(_rest(portal) + "/portals/self", {"token": token})
    user = self_doc.get("user") or {}
    username = user.get("username")
    portal_name = self_doc.get("name", "")
    if username:
        scope, clauses = f"{username}'s content", [f"owner:{username}"]
    else:
        scope, clauses = "organization", [f"orgid:{self_doc.get('id', '')}"]
    if layers_only:
        clauses.append("(" + " OR ".join(f'type:"{t}"' for t in SERVICE_TYPES) + ")")
    terms = _search_terms(text)
    if terms:
        clauses.append("(" + " AND ".join(f"title:{t}*" for t in terms) + ")")
    page = _search_page(portal, token, " AND ".join(clauses), start, num)
    page.update(scope=scope, portal_name=portal_name)
    return page


def list_service_layers(service_url: str, token: str | None = None) -> list[dict]:
    """The sublayers and tables of one Feature/Map Service, with ready URLs."""
    base = service_url.strip().rstrip("/")
    doc = _post(base, {"token": token} if token else {})
    out = []
    for group in ("layers", "tables"):
        for lyr in doc.get(group) or []:
            lid = lyr.get("id")
            out.append({
                "id": lid,
                "name": lyr.get("name") or f"layer {lid}",
                "kind": "table" if group == "tables" else "layer",
                "geometry": lyr.get("geometryType", "").replace("esriGeometry", ""),
                "url": f"{base}/{lid}",
            })
    return out
