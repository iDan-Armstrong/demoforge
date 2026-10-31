from __future__ import annotations

from demoforge.lyrx import list_fields_referenced, rewrite_datasource

LYRX = {
    "layerDefinitions": [{
        "name": "Manholes",
        "featureTable": {
            "dataConnection": {
                "workspaceConnectionString": r"DATABASE=C:\\proj\\AcmeCity.gdb",
                "dataset": "SSMH",
            }
        },
        "renderer": {
            "type": "CIMUniqueValueRenderer",
            "fields": ["INSPSTATUS"],
        },
        "labelClasses": [{
            "expression": "$feature.FACILITYID + ' (' + $feature.DEPTH + ')'",
        }],
    }]
}


def test_workspace_and_dataset_rewritten():
    out, count = rewrite_datasource(
        LYRX,
        workspace_map={r"C:\\proj\\AcmeCity.gdb": r".\\demo\\Northwood.gdb"},
        dataset_map={"SSMH": "DEMO_SSMH"},
    )
    conn = out["layerDefinitions"][0]["featureTable"]["dataConnection"]
    assert "Northwood.gdb" in conn["workspaceConnectionString"]
    assert conn["dataset"] == "DEMO_SSMH"
    assert count == 2
    # original untouched (deep copy)
    assert "AcmeCity" in LYRX["layerDefinitions"][0]["featureTable"][
        "dataConnection"]["workspaceConnectionString"]


def test_fields_referenced_by_cartography():
    fields = list_fields_referenced(LYRX)
    assert {"INSPSTATUS", "FACILITYID", "DEPTH"} <= fields
