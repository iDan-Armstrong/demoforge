from __future__ import annotations

import pytest

from demoforge.fake import FieldPolicy
from demoforge.pipeline import forge_geojson

FC = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [500000.0, 3300000.0]},
         "properties": {"PID": "P-100", "OWNER": "John Smith",
                        "NOTES": "met owner at AcmeCity office"}},
        {"type": "Feature",
         "geometry": {"type": "Polygon", "coordinates": [[
             [500000.0, 3300000.0], [501000.0, 3300000.0],
             [501000.0, 3301000.0], [500000.0, 3300000.0]]]},
         "properties": {"PID": "P-101", "OWNER": "Jane Doe", "NOTES": ""}},
    ],
}
TARGET = (-77.6, 4.0, -76.8, 4.8)
POLICIES = [FieldPolicy("OWNER", "fake:person"), FieldPolicy("PID", "fake:id_pattern")]


def test_forge_relocates_fakes_and_audits():
    result = forge_geojson(FC, seed="s1", target_bounds=TARGET,
                           policies=POLICIES, blocklist=["AcmeCity"])
    feats = result.geojson["features"]
    # relocated into target
    x, y = feats[0]["geometry"]["coordinates"]
    assert TARGET[0] <= x <= TARGET[2] and TARGET[1] <= y <= TARGET[3]
    # faked but join-stable and changed
    assert feats[0]["properties"]["OWNER"] != "John Smith"
    assert feats[0]["properties"]["PID"] != "P-100"
    # audit catches the blocklist term that survived (NOTES had no policy)
    assert any(f.kind == "blocklist" for f in result.findings)
    assert result.stats["features"] == 2
    assert result.stats["audit_findings"] == len(result.findings)


def test_shared_vertex_still_shared_after_forge():
    result = forge_geojson(FC, seed="s1", target_bounds=TARGET)
    pt = result.geojson["features"][0]["geometry"]["coordinates"]
    ring = result.geojson["features"][1]["geometry"]["coordinates"][0]
    assert pt == ring[0] == ring[3]


def test_deterministic_for_same_seed():
    a = forge_geojson(FC, seed="s1", target_bounds=TARGET, policies=POLICIES)
    b = forge_geojson(FC, seed="s1", target_bounds=TARGET, policies=POLICIES)
    assert a.geojson == b.geojson


def test_single_point_input_still_forges():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [500000.0, 3300000.0]},
         "properties": {"PID": "P-1"}}]}
    result = forge_geojson(fc, seed="s", target_bounds=TARGET)
    x, y = result.geojson["features"][0]["geometry"]["coordinates"]
    assert TARGET[0] <= x <= TARGET[2] and TARGET[1] <= y <= TARGET[3]


def test_empty_collection_rejected():
    with pytest.raises(ValueError, match="no features"):
        forge_geojson({"type": "FeatureCollection", "features": []},
                      seed="s", target_bounds=TARGET)
