# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ConditionRecord:
    """Normalised, flattened view of a FHIR Condition resource."""
    id: str
    display_text: str
    clinical_status: str             # "Active" | "Resolved" | "unknown"
    onset_start: Optional[str]
    onset_end: Optional[str]
    snomed_codes: list[str]
    icd10_codes: list[str]
    is_admin: bool
    source_identifiers: list[str]    # all identifier.value strings
    recorder_id: Optional[str]
    raw: dict                        # original FHIR resource


@dataclass
class ConceptGroup:
    """
    All ConditionRecords that share at least one SNOMED code.

    Canonical record: the one with the most source_identifiers.
    In this dataset, reconciled/merged records accumulate identifiers
    across EMR systems, making identifier count a reliable proxy for
    "most authoritative."
    """
    snomed_codes: set[str]
    records: list[ConditionRecord] = field(default_factory=list)
    retracted: bool = False          # set by user correction

    @property
    def canonical(self) -> Optional[ConditionRecord]:
        if not self.records:
            return None
        return max(self.records, key=lambda r: len(r.source_identifiers))

    @property
    def active_records(self) -> list[ConditionRecord]:
        return [r for r in self.records if r.clinical_status.lower() == "active"]

    @property
    def display(self) -> str:
        c = self.canonical
        return c.display_text if c else ""