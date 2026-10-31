"""Deterministic attribute faking: same input -> same fake output, per seed.

Determinism is the whole game. If parcel P-1042 appears in three feature
classes and a related table, every occurrence must map to the *same* fake
id or every join in the project silently breaks. So fakes are derived from
HMAC(seed, value) — stable within a run, unlinkable to the original
without the seed, and different across projects when the seed changes.

Keep the seed private: it is the only bridge back to the real values.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

FIRST = ["Avery", "Casey", "Dana", "Ellis", "Finley", "Harper", "Jordan",
         "Kendall", "Logan", "Morgan", "Parker", "Quinn", "Reese", "Rowan",
         "Sage", "Taylor"]
LAST = ["Abbott", "Barnes", "Calder", "Dalton", "Ellison", "Forsythe",
        "Granger", "Holloway", "Irwin", "Jennings", "Keating", "Lockhart",
        "Mercer", "Norwood", "Oakes", "Prescott"]
STREET = ["Alder", "Birch", "Cedar", "Dogwood", "Elm", "Fir", "Hawthorn",
          "Juniper", "Laurel", "Magnolia", "Oak", "Pine", "Rowan", "Spruce",
          "Sycamore", "Willow"]
STREET_TYPE = ["St", "Ave", "Rd", "Ln", "Ct", "Dr", "Way", "Blvd"]
PLACE = ["Northwood", "Eastmarsh", "Southvale", "Westbrook", "Cedarford",
         "Milldale", "Harborview", "Stonegate", "Fallbrook", "Kingsmere"]


def _digest(seed: str, value: str) -> bytes:
    return hmac.new(seed.encode(), value.encode(), hashlib.sha256).digest()


def _pick(options: list[str], d: bytes, i: int) -> str:
    return options[d[i] % len(options)]


@dataclass(frozen=True)
class FieldPolicy:
    """What to do with one field: keep | fake:<kind> | drop.

    kinds: person, street_address, place, id_pattern, redact
    """

    field: str
    action: str


class Faker:
    def __init__(self, seed: str):
        if not seed:
            raise ValueError("a non-empty seed is required")
        self._seed = seed

    def person(self, value: str) -> str:
        d = _digest(self._seed, "person:" + value)
        return f"{_pick(FIRST, d, 0)} {_pick(LAST, d, 1)}"

    def street_address(self, value: str) -> str:
        d = _digest(self._seed, "addr:" + value)
        number = 100 + int.from_bytes(d[2:4], "big") % 9900
        return f"{number} {_pick(STREET, d, 0)} {_pick(STREET_TYPE, d, 1)}"

    def place(self, value: str) -> str:
        d = _digest(self._seed, "place:" + value)
        return _pick(PLACE, d, 0)

    def id_pattern(self, value: str) -> str:
        """Replace digits with digits and letters with letters, preserving
        format: 'MH-1042a' -> 'MH-' stays if literal? No — every letter and
        digit is replaced; punctuation and casing structure survive, so
        downstream format validators still pass."""
        d = _digest(self._seed, "id:" + value)
        out = []
        for i, ch in enumerate(value):
            b = d[i % len(d)]
            if ch.isdigit():
                out.append(str(b % 10))
            elif ch.isalpha():
                letter = chr(ord("a") + b % 26)
                out.append(letter.upper() if ch.isupper() else letter)
            else:
                out.append(ch)
        return "".join(out)

    def apply(self, kind: str, value: object) -> object:
        if value is None or str(value).strip() == "":
            return value
        text = str(value)
        if kind == "person":
            return self.person(text)
        if kind == "street_address":
            return self.street_address(text)
        if kind == "place":
            return self.place(text)
        if kind == "id_pattern":
            return self.id_pattern(text)
        if kind == "redact":
            return "REDACTED"
        raise ValueError(f"unknown fake kind: {kind!r}")


def apply_policies(
    records: list[dict],
    policies: list[FieldPolicy],
    faker: Faker,
) -> list[dict]:
    """Return new records with policies applied; unlisted fields are KEPT,
    which is why the audit step exists — keeping is the dangerous default
    and the audit is what makes it safe."""
    by_field = {p.field: p for p in policies}
    out = []
    for rec in records:
        new = {}
        for key, value in rec.items():
            policy = by_field.get(key)
            if policy is None or policy.action == "keep":
                new[key] = value
            elif policy.action == "drop":
                continue
            elif policy.action.startswith("fake:"):
                new[key] = faker.apply(policy.action.split(":", 1)[1], value)
            else:
                raise ValueError(f"unknown action {policy.action!r} for {key!r}")
        out.append(new)
    return out
