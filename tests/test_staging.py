from __future__ import annotations

import ast
from pathlib import Path

from demoforge.staging import build_job_config, suggest_policies, suggest_policy


def actions(fields):
    return {f: suggest_policy(f)["action"] for f in fields}


def policy_actions(fields, geometry_type=""):
    return {p["field"]: p["action"]
            for p in suggest_policies(fields, geometry_type=geometry_type)}


def test_policy_suggestions_by_field_name():
    got = actions(["OWNER_NAME", "SITE_ADDRESS", "CITY", "PHONE",
                   "FACILITYID", "DIAMETER", "OBJECTID"])
    assert got["OWNER_NAME"] == "fake:person"
    assert got["SITE_ADDRESS"] == "fake:street_address"
    assert got["CITY"] == "fake:place"
    assert got["PHONE"] == "fake:redact"
    assert got["FACILITYID"] == "fake:id_pattern"
    assert got["DIAMETER"] == "keep"
    assert got["OBJECTID"] == "drop"


def test_place_layer_names_are_places_not_people():
    # the Colonial Beach boundary case: NAME is a place, GNIS/FIPS identify it
    fields = ["NAME", "NAMELSAD", "GNIS", "STPLFIPS", "FID", "AREASQMI", "OBJECTID"]
    pol = policy_actions(fields, geometry_type="Polygon")
    assert pol["NAME"] == "fake:place"        # not fake:person
    assert pol["NAMELSAD"] == "fake:place"
    assert pol["GNIS"] == "fake:id_pattern"   # geographic id, not keep
    assert pol["STPLFIPS"] == "fake:id_pattern"
    assert pol["FID"] == "fake:id_pattern"
    assert pol["AREASQMI"] == "keep"
    assert pol["OBJECTID"] == "drop"


def test_owner_layer_names_stay_people():
    # owner/parcel context vetoes the place reading — NAME is a person here
    pol = policy_actions(["NAME", "OWNER", "SITE_ADDRESS", "APN"],
                         geometry_type="Polygon")
    assert pol["NAME"] == "fake:person"
    assert pol["OWNER"] == "fake:person"
    assert pol["SITE_ADDRESS"] == "fake:street_address"


def test_geometry_disambiguates_a_bare_name():
    # a polygon area with just a name -> place; a point with a name -> person
    assert policy_actions(["NAME", "ZONE"], "Polygon")["NAME"] == "fake:place"
    assert policy_actions(["NAME", "PHONE"], "Point")["NAME"] == "fake:person"


def test_every_suggestion_has_a_reason():
    for field in ["OWNER", "Shape_Area", "NOTES", "beds"]:
        s = suggest_policy(field)
        assert s["reason"], field


def test_job_config_shape():
    job = build_job_config(
        {"SSMH": ["FACILITYID", "DEPTH"], "Parcels": ["OWNER", "ACRES"]},
        source_workspace="C:/proj/city.gdb",
    )
    assert job["demoforge_job"] == 1
    assert set(job["layers"]) == {"SSMH", "Parcels"}
    assert job["layers"]["SSMH"]["geojson"] == "SSMH.geojson"
    pol = {p["field"]: p["action"] for p in job["layers"]["Parcels"]["policies"]}
    assert pol["OWNER"] == "fake:person" and pol["ACRES"] == "keep"
    assert "CHANGE-ME" in job["seed"]


def test_extract_pyt_structure():
    """Same AST discipline as the other toolboxes: CI can't import arcpy,
    but it can verify the .pyt's tool protocol."""
    pyt = Path(__file__).parents[1] / "toolbox" / "DemoForgeExtract.pyt"
    tree = ast.parse(pyt.read_text(), filename=str(pyt))
    classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert "Toolbox" in classes and "ExtractToDemoforge" in classes
    methods = {n.name for n in classes["ExtractToDemoforge"].body
               if isinstance(n, ast.FunctionDef)}
    assert {"__init__", "getParameterInfo", "execute"} <= methods
