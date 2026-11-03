"""Fetch hosted feature layers over the Esri REST API (stdlib only).

Pulls a whole layer (``.../FeatureServer/<idx>``) as a GeoJSON
FeatureCollection, paging with ``resultOffset`` at the server's own
``maxRecordCount``, authenticated by whatever token the caller supplies, or by none for public
layers (see :func:`demoforge.ago.get_token`).

Known limitation: this asks the server
for ``f=geojson``, which ArcGIS Online and recent Portals support. A
server that can't speak GeoJSON gets a clear error, not a half-right
conversion.
"""

from __future__ import annotations

from demoforge.ago import AgoError, _post

_PAGE_CAP = 2000  # never ask for more than this per request, whatever the server says


def layer_info(layer_url: str, token: str | None = None) -> dict:
    """Layer metadata: {'name', 'max_record_count', 'supports_geojson'}."""
    url = layer_url.strip().rstrip("/")
    params: dict = {}
    if token:
        params["token"] = token
    doc = _post(url, params)
    formats = (doc.get("supportedQueryFormats") or "").replace(" ", "").lower()
    return {
        "name": doc.get("name") or url.rsplit("/", 2)[-2],
        "max_record_count": int(doc.get("maxRecordCount") or 1000),
        "supports_geojson": "geojson" in formats,
    }


def fetch_layer_geojson(
    layer_url: str,
    token: str | None = None,
    where: str = "1=1",
    on_page=None,
) -> tuple[str, dict]:
    """Pull every feature. Returns (layer_name, FeatureCollection).

    ``on_page(fetched_so_far)`` is called after each page; the toolbox
    uses it for progress messages.
    """
    url = layer_url.strip().rstrip("/")
    info = layer_info(url, token)
    if not info["supports_geojson"]:
        raise AgoError(
            f"layer {info['name']!r} does not offer GeoJSON "
            "(supportedQueryFormats); extract it via the map in ArcGIS Pro instead"
        )
    page = min(info["max_record_count"], _PAGE_CAP)

    features: list = []
    while True:
        params = {
            "f": "geojson",
            "where": where,
            "outFields": "*",
            "returnGeometry": "true",
            "resultOffset": len(features),
            "resultRecordCount": page,
        }
        if token:
            params["token"] = token
        doc = _post(url + "/query", params)
        batch = doc.get("features", [])
        features.extend(batch)
        if on_page:
            on_page(len(features))
        if len(batch) < page:
            break
    return info["name"], {"type": "FeatureCollection", "features": features}
