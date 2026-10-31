"""Relocation: one affine transform moves the whole project to a fictional AOI.

Why affine and not per-feature jitter: an affine transform (translate,
rotate, uniform scale) preserves *every* internal spatial relationship —
shared parcel boundaries stay shared, pipes stay connected to manholes,
containment and adjacency survive untouched. Jitter destroys exactly the
topology that makes GIS data coherent; v2 may add topology-aware morphing,
but v1 refuses to break what works.

Pure math over (x, y) tuples / nested coordinate arrays, so the same
planner serves the arcpy adapter, GeoJSON, or anything else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Bounds = tuple[float, float, float, float]  # minx, miny, maxx, maxy


@dataclass(frozen=True)
class AffineTransform:
    """x' = a*x + b*y + xoff ; y' = c*x + d*y + yoff"""

    a: float
    b: float
    c: float
    d: float
    xoff: float
    yoff: float

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.b * y + self.xoff,
                self.c * x + self.d * y + self.yoff)

    def apply_coords(self, coords):
        """Recursively transform GeoJSON-style nested coordinate arrays."""
        if not coords:
            return coords
        if isinstance(coords[0], (int, float)):
            x, y = self.apply(coords[0], coords[1])
            # preserve any Z/M values untouched
            return [x, y, *coords[2:]]
        return [self.apply_coords(c) for c in coords]


def plan_relocation(
    source: Bounds,
    target: Bounds,
    rotation_deg: float = 0.0,
    fit: str = "contain",
) -> AffineTransform:
    """Build the transform that moves ``source`` into ``target``.

    fit="contain": uniform scale so the (rotated) source fits inside the
    target, centered. Uniform scaling only — distorting aspect ratio would
    make circles into ellipses and square parcels into rhombi, which reads
    as *wrong* to any GIS eye.
    """
    if fit != "contain":
        raise ValueError(f"unsupported fit mode: {fit!r}")
    sminx, sminy, smaxx, smaxy = source
    tminx, tminy, tmaxx, tmaxy = target
    sw, sh = smaxx - sminx, smaxy - sminy
    tw, th = tmaxx - tminx, tmaxy - tminy
    if sw <= 0 or sh <= 0 or tw <= 0 or th <= 0:
        raise ValueError("source and target bounds must have positive extent")

    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    # extent of the source after rotation about its center
    rot_w = abs(sw * cos_t) + abs(sh * sin_t)
    rot_h = abs(sw * sin_t) + abs(sh * cos_t)
    scale = min(tw / rot_w, th / rot_h)

    # compose: translate source center to origin -> rotate -> scale ->
    # translate to target center
    scx, scy = (sminx + smaxx) / 2, (sminy + smaxy) / 2
    tcx, tcy = (tminx + tmaxx) / 2, (tminy + tmaxy) / 2

    a = scale * cos_t
    b = -scale * sin_t
    c = scale * sin_t
    d = scale * cos_t
    xoff = tcx - (a * scx + b * scy)
    yoff = tcy - (c * scx + d * scy)
    return AffineTransform(a, b, c, d, xoff, yoff)
