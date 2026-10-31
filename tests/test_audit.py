from __future__ import annotations

from demoforge.audit import audit_records, to_markdown


def kinds(findings):
    return {f.kind for f in findings}


def test_blocklist_term_found_case_insensitive():
    recs = [{"NOTES": "Spoke with ACME Utilities about the lift station"}]
    findings = audit_records(recs, blocklist=["acme utilities"],
                             check_field_names=False)
    assert kinds(findings) == {"blocklist"}
    assert "ACME Utilities" in findings[0].excerpt


def test_email_phone_ssn_patterns():
    recs = [{
        "A": "contact bob@example.com for access",
        "B": "call (409) 555-0142 after 5",
        "C": "ref 123-45-6789 on file",
    }]
    findings = audit_records(recs, check_field_names=False)
    assert kinds(findings) == {"email", "phone", "ssn_pattern"}


def test_sensitive_field_names_flagged_once():
    recs = [{"OWNER_NAME": "x", "SHAPE_LEN": 1.0}, {"OWNER_NAME": "y", "SHAPE_LEN": 2.0}]
    findings = audit_records(recs)
    schema = [f for f in findings if f.record == "schema"]
    assert len(schema) == 1 and schema[0].field == "OWNER_NAME"


def test_clean_records_produce_clean_report():
    recs = [{"TYPE": "clinic", "BEDS": 10}]
    findings = audit_records(recs, blocklist=["ACME"], check_field_names=False)
    assert findings == []
    assert "CLEAN" in to_markdown(findings)


def test_markdown_lists_every_finding():
    recs = [{"NOTES": "bob@example.com"}]
    findings = audit_records(recs, check_field_names=False)
    md = to_markdown(findings)
    assert "1 finding" in md and "email" in md
