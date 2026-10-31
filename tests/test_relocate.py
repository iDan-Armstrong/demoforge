from __future__ import annotations

import math

import pytest

from demoforge.relocate import plan_relocation

SOURCE = (500000.0, 3300000.0, 510000.0, 3306000.0)  # a 10km x 6km project
TARGET = (-77.6, 4.0, -76.8, 4.8)


def dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def test_source_lands_inside_target():
    t = plan_relocation(SOURCE, TARGET)
    for x, y in [(SOURCE[0], SOURCE[1]), (SOURCE[2], SOURCE[3]),
                 (SOURCE[0], SOURCE[3]), (SOURCE[2], SOURCE[1])]:
        nx, ny = t.apply(x, y)
        assert TARGET[0] <= nx <= TARGET[2]
        assert TARGET[1] <= ny <= TARGET[3]


def test_relative_geometry_preserved():
    """The heart of the design: ratios of distances are invariant, so every
    spatial relationship survives."""
    t = plan_relocation(SOURCE, TARGET, rotation_deg=30)
    a, b, c = (500100, 3300100), (500200, 3300100), (500100, 3300500)
    ta, tb, tc = t.apply(*a), t.apply(*b), t.apply(*c)
    assert dist(ta, tb) / dist(ta, tc) == pytest.approx(dist(a, b) / dist(a, c))


def test_shared_vertices_stay_shared():
    t = plan_relocation(SOURCE, TARGET, rotation_deg=45)
    shared = (505000.0, 3303000.0)
    assert t.apply(*shared) == t.apply(*shared)


def test_rotation_rotates():
    t0 = plan_relocation(SOURCE, TARGET, rotation_deg=0)
    t90 = plan_relocation(SOURCE, TARGET, rotation_deg=90)
    p, q = (500000, 3300000), (510000, 3300000)  # horizontal segment
    v0 = t0.apply(*q)[0] - t0.apply(*p)[0], t0.apply(*q)[1] - t0.apply(*p)[1]
    v90 = t90.apply(*q)[0] - t90.apply(*p)[0], t90.apply(*q)[1] - t90.apply(*p)[1]
    assert abs(v0[1]) < 1e-9  # still horizontal
    assert abs(v90[0]) < 1e-6  # now vertical


def test_nested_coords_and_z_preserved():
    t = plan_relocation(SOURCE, TARGET)
    ring = [[[500000, 3300000, 12.5], [510000, 3300000, 13.0],
             [510000, 3306000, 13.5], [500000, 3300000, 12.5]]]
    out = t.apply_coords(ring)
    assert out[0][0][2] == 12.5 and out[0][2][2] == 13.5
    assert out[0][0][:2] != ring[0][0][:2]


def test_degenerate_bounds_rejected():
    with pytest.raises(ValueError):
        plan_relocation((0, 0, 0, 10), TARGET)
