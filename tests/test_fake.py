from __future__ import annotations

import pytest

from demoforge.fake import Faker, FieldPolicy, apply_policies


def test_deterministic_within_seed():
    f = Faker("seed-1")
    assert f.person("John Smith") == f.person("John Smith")
    assert f.id_pattern("MH-1042") == f.id_pattern("MH-1042")


def test_different_across_seeds():
    a, b = Faker("seed-1"), Faker("seed-2")
    assert a.person("John Smith") != b.person("John Smith")


def test_fake_differs_from_original():
    f = Faker("seed-1")
    assert f.person("John Smith") != "John Smith"


def test_id_pattern_preserves_format():
    f = Faker("seed-1")
    fake = f.id_pattern("MH-1042a")
    assert len(fake) == len("MH-1042a")
    assert fake[2] == "-"
    assert fake[:2].isalpha() and fake[:2].isupper()
    assert fake[3:7].isdigit()
    assert fake[7].isalpha() and fake[7].islower()


def test_joins_survive_faking():
    """Same real ID in two 'tables' maps to the same fake ID."""
    f = Faker("seed-1")
    parcels = [{"PID": "P-100", "OWNER": "John Smith"}]
    permits = [{"PID": "P-100", "TYPE": "deck"}]
    pol = [FieldPolicy("PID", "fake:id_pattern"), FieldPolicy("OWNER", "fake:person")]
    out_parcels = apply_policies(parcels, pol, f)
    out_permits = apply_policies(permits, pol, f)
    assert out_parcels[0]["PID"] == out_permits[0]["PID"]
    assert out_parcels[0]["PID"] != "P-100"


def test_drop_and_keep_and_nulls():
    f = Faker("s")
    records = [{"KEEP": 5, "GONE": "x", "NAME": None}]
    pol = [FieldPolicy("GONE", "drop"), FieldPolicy("NAME", "fake:person")]
    out = apply_policies(records, pol, f)
    assert out == [{"KEEP": 5, "NAME": None}]


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown fake kind"):
        Faker("s").apply("vibes", "x")


def test_empty_seed_rejected():
    with pytest.raises(ValueError):
        Faker("")
