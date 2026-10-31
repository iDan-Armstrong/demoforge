"""demoforge: turn proprietary GIS projects into shareable demo data.

The pipeline: **relocate** geometry to a fictional AOI (affine, so every
spatial relationship survives) → **fake** identifying attributes
(deterministically, so joins survive) → **audit** what's left for leaks
(the report a human signs off on) → optionally **dirty** the result for
QA demos.

Anonymized is not the same as non-proprietary: this tool removes
*identifiability*; your contract decides *ownership*. The audit report
exists so that sign-off is informed, not assumed.
"""

from demoforge.audit import AuditFinding, audit_records
from demoforge.fake import Faker, FieldPolicy
from demoforge.relocate import AffineTransform, plan_relocation

__all__ = [
    "AffineTransform",
    "AuditFinding",
    "Faker",
    "FieldPolicy",
    "audit_records",
    "plan_relocation",
]

__version__ = "0.1.0"
