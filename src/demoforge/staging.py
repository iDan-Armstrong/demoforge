"""Staging: the contract between the Pro extraction tool and the workbench.

The Pro .pyt exports each selected layer (local FC, hosted feature layer,
or every FC in a geodatabase) to GeoJSON in a staging folder, plus one
``demoforge_job.json`` describing the whole job: per-layer field policies
(auto-drafted here, human-edited after), blocklist, seed placeholder,
target bounds. The workbench loads the same files; the forge runs from the
same config. One contract, three consumers.

Policy drafting is deliberately conservative: it *suggests*, flags why,
and defaults anything suspicious to a fake rather than a keep — the human
can always relax it. It is also context-aware: a bare ``NAME`` means a
*place* in a boundary layer but a *person* in a parcel/owner layer, and
geographic identifiers (GNIS, FIPS, GEOID) are anonymized, not kept.
Pure Python, fully tested, no AI — HMAC + rules all the way down.
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

# geographic identifiers: a format-preserving fake keeps joins and the look
# of the value while removing the link back to a real place. These slip past
# the generic "id" hint because the names don't contain "id".
_GEO_ID_HINTS = ("gnis", "geoid", "ansicode", "fips", "statefp", "placefp",
                 "countyfp")

# fields that mark a layer as being about PLACES (so a bare "name" is a place)
_PLACE_CONTEXT = ("gnis", "namelsad", "geoid", "fips", "statefp", "placefp",
                  "lsad", "classfp")

# fields that mark a layer as being about PEOPLE / ownership
_OWNER_HINTS = ("owner", "parcel", "apn", "applicant", "tenant", "resident",
                "customer", "grantee", "grantor", "occupant")


def _any_hint(lowered_fields: set[str], hints: tuple[str, ...]) -> bool:
    return any(h in f for f in lowered_fields for h in hints)


def _is_place_layer(lowered_fields: set[str], geometry_type: str = "") -> bool:
    """A layer about places (so a bare NAME is a place name, not a person).

    Owner/parcel signals veto it outright. Otherwise census/USGS place
    fields confirm it; failing that, a polygon area carrying a name but no
    owner or address signals is treated as a place/zone — the geometry is
    the tiebreaker, since a person never *is* a geographic area.
    """
    if _any_hint(lowered_fields, _OWNER_HINTS):
        return False
    if _any_hint(lowered_fields, _PLACE_CONTEXT):
        return True
    is_area = geometry_type.lower() in ("polygon", "multipolygon")
    has_name = _any_hint(lowered_fields, ("name",))
    has_addr = _any_hint(lowered_fields, ("address", "addr", "street"))
    return is_area and has_name and not has_addr


def suggest_policy(field: str, *, place_layer: bool = False) -> dict[str, str]:
    """One field -> {field, action, reason}, given its layer's context."""
    lowered = field.lower()
    if lowered in SYSTEM_FIELDS:
        return {"field": field, "action": "drop",
                "reason": "geodatabase system field"}
    for hint in _GEO_ID_HINTS:
        if hint in lowered:
            return {"field": field, "action": "fake:id_pattern",
                    "reason": f"geographic identifier (contains {hint!r})"}
    if "namelsad" in lowered:
        return {"field": field, "action": "fake:place",
                "reason": "census place-name field"}
    is_owner_field = any(h in lowered for h in _OWNER_HINTS)
    if place_layer and "name" in lowered and not is_owner_field:
        return {"field": field, "action": "fake:place",
                "reason": "name in a place/boundary layer"}
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


def suggest_policies(fields: list[str], *,
                     geometry_type: str = "") -> list[dict[str, str]]:
    """Draft policies for a whole layer, using the field set + geometry
    for context (so NAME resolves to place vs person correctly)."""
    lowered = {f.lower() for f in fields}
    place_layer = _is_place_layer(lowered, geometry_type)
    return [suggest_policy(f, place_layer=place_layer) for f in fields]


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
                "policies": suggest_policies(fields),
            }
            for name, fields in layers.items()
        },
        "_note": (
            "Review every policy and the blocklist before forging. "
            "Suggestions are drafts, not decisions."
        ),
    }
