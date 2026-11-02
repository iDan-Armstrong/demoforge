"""Orchestration: run the full forge over a GeoJSON FeatureCollection.

GeoJSON is the dev-time format: the arcpy adapter reads feature classes
into the same shapes, so everything proven here holds in Pro. The order is
deliberate — relocate, then fake, then audit — because the audit must see
the *output* (what will actually ship), not the input.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from demoforge.audit import AuditFinding, audit_records
from demoforge.fake import Faker, FieldPolicy, apply_policies
from demoforge.relocate import Bounds, plan_relocation


@dataclass
class ForgeResult:
    geojson: dict
    findings: list[AuditFinding]
    stats: dict = field(default_factory=dict)


def _collect_bounds(features: list[dict]) -> Bounds:
    xs: list[float] = []
    ys: list[float] = []

    def walk(coords):
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            xs.append(coords[0])
            ys.append(coords[1])
        else:
            for c in coords:
                walk(c)

    for f in features:
        geom = f.get("geometry")
        if geom:
            walk(geom.get("coordinates"))
    if not xs:
        raise ValueError("no coordinates found in input")
    minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
    # pad degenerate extents (single point, collinear features) so the
    # affine planner always has a real box to work with
    pad_x = (maxx - minx) or 1.0
    pad_y = (maxy - miny) or 1.0
    if maxx - minx == 0:
        minx, maxx = minx - pad_x / 2, maxx + pad_x / 2
    if maxy - miny == 0:
        miny, maxy = miny - pad_y / 2, maxy + pad_y / 2
    return (minx, miny, maxx, maxy)


def forge_geojson(
    geojson: dict,
    *,
    seed: str,
    target_bounds: Bounds,
    rotation_deg: float = 0.0,
    scramble: float = 0.0,
    policies: list[FieldPolicy] | None = None,
    blocklist: list[str] | None = None,
) -> ForgeResult:
    features = geojson.get("features", [])
    if not features:
        raise ValueError("FeatureCollection has no features")

    source = _collect_bounds(features)
    transform = plan_relocation(source, target_bounds, rotation_deg,
                                scramble=scramble, seed=seed)
    faker = Faker(seed)
    policies = policies or []

    records = [dict(f.get("properties") or {}) for f in features]
    forged_records = apply_policies(records, policies, faker)

    out_features = []
    for f, props in zip(features, forged_records):
        geom = f.get("geometry")
        new_geom = None
        if geom:
            new_geom = {
                "type": geom["type"],
                "coordinates": transform.apply_coords(geom["coordinates"]),
            }
        out_features.append(
            {"type": "Feature", "geometry": new_geom, "properties": props}
        )

    findings = audit_records(forged_records, blocklist=blocklist)
    faked = sum(1 for p in policies if p.action.startswith("fake:"))
    dropped = sum(1 for p in policies if p.action == "drop")
    return ForgeResult(
        geojson={"type": "FeatureCollection", "features": out_features},
        findings=findings,
        stats={
            "features": len(out_features),
            "source_bounds": source,
            "target_bounds": target_bounds,
            "fields_faked": faked,
            "fields_dropped": dropped,
            "audit_findings": len(findings),
            "scramble": scramble,
        },
    )
