"""Leak audit: find what the scrubber did NOT handle, and make it visible.

The dangerous failure mode of any anonymizer is false confidence: the
coordinates moved, the names changed, and a client's name is still sitting
in a free-text NOTES field from 2019. The audit's job is to surface every
such survivor so a human signs off per item. It checks:

- a blocklist of terms you supply (client names, project names, towns)
- PII-shaped patterns: emails, phone numbers, SSN-shaped strings
- field *names* that suggest sensitive content (owner, contact, phone...)

It reports; it never silently fixes. Fixing is a policy decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"\b(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

SENSITIVE_FIELD_HINTS = (
    "owner", "contact", "phone", "email", "name", "address", "applicant",
    "tenant", "customer", "resident", "account", "parcel_id", "taxid",
)


@dataclass(frozen=True)
class AuditFinding:
    record: int | str  # record index or "schema"/"metadata"
    field: str
    kind: str  # blocklist | email | phone | ssn_pattern | field_name
    excerpt: str


def _excerpt(text: str, start: int, end: int, radius: int = 24) -> str:
    s, e = max(0, start - radius), min(len(text), end + radius)
    return ("…" if s > 0 else "") + text[s:e] + ("…" if e < len(text) else "")


def audit_records(
    records: list[dict],
    blocklist: list[str] | None = None,
    check_field_names: bool = True,
) -> list[AuditFinding]:
    blocklist = [t for t in (blocklist or []) if t.strip()]
    block_res = [re.compile(re.escape(t), re.IGNORECASE) for t in blocklist]
    findings: list[AuditFinding] = []

    if check_field_names and records:
        for field in records[0]:
            lowered = field.lower()
            if any(h in lowered for h in SENSITIVE_FIELD_HINTS):
                findings.append(AuditFinding(
                    "schema", field, "field_name",
                    f"field name {field!r} suggests sensitive content — "
                    "confirm it has a policy"))

    patterns = [
        ("email", EMAIL_RE), ("phone", PHONE_RE), ("ssn_pattern", SSN_RE),
    ]
    for i, rec in enumerate(records):
        for field, value in rec.items():
            if value is None:
                continue
            text = str(value)
            for term_re in block_res:
                m = term_re.search(text)
                if m:
                    findings.append(AuditFinding(
                        i, field, "blocklist", _excerpt(text, m.start(), m.end())))
            for kind, pattern in patterns:
                m = pattern.search(text)
                if m:
                    findings.append(AuditFinding(
                        i, field, kind, _excerpt(text, m.start(), m.end())))
    return findings


def to_markdown(findings: list[AuditFinding]) -> str:
    lines = [
        "# demoforge leak audit",
        "",
        ("**CLEAN** — no findings. Still read the output with human eyes "
         "before sharing." if not findings else
         f"**{len(findings)} finding(s)** — every one needs a human decision "
         "before this output ships."),
        "",
    ]
    if findings:
        lines += ["| record | field | kind | excerpt |", "|---|---|---|---|"]
        for f in findings:
            lines.append(f"| {f.record} | {f.field} | {f.kind} | {f.excerpt} |")
    return "\n".join(lines) + "\n"
