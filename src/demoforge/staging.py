"""Staging: the contract between the Pro extraction tool and the workbench.

The Pro .pyt exports each selected layer (local FC, hosted feature layer,
or every FC in a geodatabase) to GeoJSON in a staging folder, plus one
``demoforge_job.json`` describing the whole job: per-layer field policies
(auto-drafted here, human-edited after), blocklist, seed placeholder,
target bounds. The workbench loads the same files; the forge runs from the
same config. One contract, three consumers.

Policy drafting is deliberately conservative: it *suggests*, flags why,
and defaults anything suspicious to a fake rather than a keep — the human
can always relax it. Pure Python, fully tested.
"""

from __future__ import annotations

from typing import Any

from demoforge.audit import SENSITIVE_FIELD_HINTS

# field-name fragments -> suggested fake kind (checked in order)
_KIND_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("address", "addr", "street"), "fake:street_address"),
    (("owner", "name", "contact", "applicant", "tenant", "customer",
      "resident"), "fake:person"),
    (("city", "town", "place", "community", "subdivision"), "fake:place"),
    (("phone", "email", "account", "taxid", "ssn"), "fake:redact"),
    (("id", "facilityid", "parcel", "pid", "assetid", "sourceoid"),
     "fake:id_pattern"),
]

SYSTEM_FIELDS = {"objectid", "shape", "shape_length", "shape_area", "globalid",
                 "created_user", "created_date", "last_edited_user",
                 "last_edited_date"}


def suggest_policy(field: str) -> dict[str, str]:
    """One field -> {field, action, reason}."""
    lowered = field.lower()
    if lowered in SYSTEM_FIELDS:
        return {"field": field, "action": "drop",
                "reason": "geodatabase system field"}
    for fragments, action in _KIND_HINTS:
        for frag in fragments:
            if frag in lowered:
                return {"field": field, "action": action,
                        "reason": f"field name contains {frag!r}"}
    if any(h in lowered for h in SENSITIVE_FIELD_HINTS):
        return {"field": field, "action": "fake:redact",
                "reason": "sensitive-looking field with no specific kind"}
    return {"field": field, "action": "keep",
            "reason": "no sensitivity signal; audit will double-check values"}


def build_job_config(
    layers: dict[str, list[str]],
    *,
    source_workspace: str = "",
) -> dict[str, Any]:
    """Draft the demoforge_job.json for a set of extracted layers."""
    return {
        "demoforge_job": 1,
        "source_workspace": source_workspace,
        "seed": "CHANGE-ME-AND-KEEP-PRIVATE",
        "target_bounds": [-77.6, 4.0, -76.8, 4.8],
        "rotation_deg": 15,
        "blocklist": ["ADD CLIENT NAMES", "ADD PROJECT NAMES", "ADD TOWNS"],
        "layers": {
            name: {
                "geojson": f"{name}.geojson",
                "policies": [suggest_policy(f) for f in fields],
            }
            for name, fields in layers.items()
        },
        "_note": (
            "Review every policy and the blocklist before forging. "
            "Suggestions are drafts, not decisions."
        ),
    }
