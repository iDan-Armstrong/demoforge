"""Relocation: one affine transform moves the whole project to a fictional AOI.

Why affine and not per-feature jitter: an affine transform (translate,
rotate, scale, shear) preserves *every* internal spatial relationship:
shared parcel boundaries stay shared, pipes stay connected to manholes,
containment and adjacency survive untouched. Per-vertex jitter destroys
exactly the topology that makes GIS data coherent; v1 refuses to.

A pure similarity move (uniform scale + rotate) preserves the shape
*exactly*, so a distinctive outline is still recognizable after
relocating. ``scramble`` adds a seed-driven anisotropic scale + shear
to defeat that: it stretches and skews the whole project so the shape no
longer matches the original, while staying a single affine map, so
topology is still exact. It is deterministic in the seed (reproducible,
reversible with the seed) but not a guessable function of the setting.
The trade-off: higher scramble reads as less geometrically
natural (circles become ellipses, squares become parallelograms), and
because it is a global linear map it defends against casual
identification, not a determined analyst with normalization tools;
non-linear topology-aware morphing is the v2 direction.

Pure math over (x, y) tuples / nested coordinate arrays, so the same
planner serves the arcpy adapter, GeoJSON, or anything else.
"""

from __future__ import annotations

import hashlib
import hmac
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

    def compose(self, inner: AffineTransform) -> AffineTransform:
        """Return self ∘ inner (apply ``inner`` first, then ``self``)."""
        return AffineTransform(
            a=self.a * inner.a + self.b * inner.c,
            b=self.a * inner.b + self.b * inner.d,
            c=self.c * inner.a + self.d * inner.c,
            d=self.c * inner.b + self.d * inner.d,
            xoff=self.a * inner.xoff + self.b * inner.yoff + self.xoff,
            yoff=self.c * inner.xoff + self.d * inner.yoff + self.yoff,
        )


def _seed_unit(seed: str, tag: str) -> float:
    """A deterministic value in [-1, 1] from the seed (same bridge as faking)."""
    digest = hmac.new(seed.encode(), tag.encode(), hashlib.sha256).digest()
    n = int.from_bytes(digest[:8], "big")
    return (n / (2**64 - 1)) * 2 - 1


def _scramble_transform(seed: str, intensity: float, center: tuple[float, float]
                        ) -> AffineTransform:
    """Anisotropic scale + shear about ``center``, magnitude set by intensity.

    Still a single affine map, so topology survives; the factors come from
    the seed so the distortion differs per project and isn't a guessable
    function of the intensity setting.
    """
    t = max(0.0, min(1.0, intensity))
    sx = 1.0 + t * 0.5 * _seed_unit(seed, "scramble:sx")   # ±50% aspect at 100%
    sy = 1.0 + t * 0.5 * _seed_unit(seed, "scramble:sy")
    gx = t * 0.45 * _seed_unit(seed, "scramble:gx")        # ±0.45 shear at 100%
    gy = t * 0.45 * _seed_unit(seed, "scramble:gy")
    cx, cy = center
    # M (scale+shear) about center: translate(-c) -> M -> translate(+c)
    m = AffineTransform(sx, gx, gy, sy, 0.0, 0.0)
    to_origin = AffineTransform(1, 0, 0, 1, -cx, -cy)
    back = AffineTransform(1, 0, 0, 1, cx, cy)
    return back.compose(m).compose(to_origin)


def plan_relocation(
    source: Bounds,
    target: Bounds,
    rotation_deg: float = 0.0,
    fit: str = "contain",
    scramble: float = 0.0,
    seed: str = "",
) -> AffineTransform:
    """Build the transform that moves ``source`` into ``target``.

    fit="contain": uniform scale so the (rotated) source fits inside the
    target, centered.

    scramble (0..1): when > 0, compose a seed-driven anisotropic scale +
    shear about the target center so the output shape no longer matches the
    original. Still affine (topology preserved); 0 keeps the shape exact.
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
    base = AffineTransform(a, b, c, d, xoff, yoff)

    if scramble > 0 and seed:
        distort = _scramble_transform(seed, scramble, (tcx, tcy))
        return distort.compose(base)
    return base
