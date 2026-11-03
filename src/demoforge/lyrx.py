"""Symbology carryover: rewrite .lyrx layer files to point at forged data.

A .lyrx is CIM JSON. Renderers, label classes, popups and field aliases are
keyed to *field names*, so as long as demoforge keeps the schema (and it
does; faking changes values, not fields), carrying the cartography over is
a matter of rewriting dataset paths. Pure JSON work: no arcpy, fully
CI-testable.
"""

from __future__ import annotations

import json
from typing import Any


def _walk(node: Any, visit) -> None:
    if isinstance(node, dict):
        visit(node)
        for v in node.values():
            _walk(v, visit)
    elif isinstance(node, list):
        for v in node:
            _walk(v, visit)


def rewrite_datasource(
    lyrx_json: dict,
    workspace_map: dict[str, str],
    dataset_map: dict[str, str] | None = None,
) -> tuple[dict, int]:
    """Return (new lyrx dict, replacement count).

    workspace_map: old workspace path/connection -> new one (exact match on
    the workspace portion of CIM data connections).
    dataset_map: optionally rename datasets (old FC name -> new FC name).
    """
    doc = json.loads(json.dumps(lyrx_json))  # deep copy
    dataset_map = dataset_map or {}
    count = 0

    def visit(node: dict) -> None:
        nonlocal count
        # CIM data connections carry workspaceConnectionString + dataset
        if "workspaceConnectionString" in node:
            conn = node["workspaceConnectionString"]
            for old, new in workspace_map.items():
                if old in conn:
                    node["workspaceConnectionString"] = conn.replace(old, new)
                    count += 1
        if "dataset" in node and node["dataset"] in dataset_map:
            node["dataset"] = dataset_map[node["dataset"]]
            count += 1

    _walk(doc, visit)
    return doc, count


def list_fields_referenced(lyrx_json: dict) -> set[str]:
    """Field names the cartography depends on (renderer fields, label
    expressions' obvious $feature references). Used to verify no fake/drop
    policy breaks the symbology."""
    fields: set[str] = set()

    def visit(node: dict) -> None:
        for key in ("field", "fieldName", "normalizationField"):
            v = node.get(key)
            if isinstance(v, str) and v:
                fields.add(v)
        if isinstance(node.get("fields"), list):
            fields.update(f for f in node["fields"] if isinstance(f, str))
        expr = node.get("expression")
        if isinstance(expr, str):
            import re
            fields.update(re.findall(r"\$feature\.(\w+)", expr))

    _walk(lyrx_json, visit)
    return fields
