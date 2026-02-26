# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

import threading
import time
from datetime import datetime
from typing import Optional
from conditions.models import ConditionRecord, ConceptGroup
from conditions.constants import ( SNOMED_SYSTEM, ICD10_SYSTEM, ADMIN_CODES, )


class ConditionStore:
    """
    Thread-safe, live store for FHIR Condition resources.

    Key design choices for latency:
    ─────────────────────────────────
    • All lookups are O(1) or O(groups) — no sequential scans over raw records.
    • `query()` never blocks on ingestion; callers get a `partial` flag instead.
    • `retract_concept()` is a simple flag flip — O(groups).
    • `ingest_batch()` runs under a single RLock, but batches are processed
      synchronously so callers can pipeline: ingest day1 → query → ingest day2.
    • For async use, call `ingest_batch()` in a background thread; queries
      will return partial=True with whatever has been ingested so far.
    """

    def __init__(self):
        self._lock = threading.RLock()
        # Primary index: condition id → ConditionRecord
        self._by_id: dict[str, ConditionRecord] = {}
        # Inverted index: snomed_code → group_key
        self._snomed_to_group: dict[str, str] = {}
        # Concept groups: group_key → ConceptGroup
        self._groups: dict[str, ConceptGroup] = {}

        # Monitoring
        self.ingestion_log: list[dict] = []
        self._ingestion_complete = False

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_batch(self, records: list[dict], batch_label: str = "batch"):
        """
        Ingest a list of raw FHIR Condition dicts.

        Thread-safe; can be called from a background thread while the main
        thread is already issuing queries. The `partial` flag in query results
        will be True until `mark_ingestion_complete()` is called.
        """
        t0 = time.monotonic()
        added, skipped, errors = 0, 0, []

        for raw in records:
            try:
                rec = self._parse(raw)
                self._upsert(rec)
                added += 1
            except Exception as e:
                errors.append({"id": raw.get("id"), "error": str(e)})
                skipped += 1

        elapsed = time.monotonic() - t0
        with self._lock:
            self.ingestion_log.append({
                "batch": batch_label,
                "timestamp": datetime.now().isoformat(),
                "added": added,
                "skipped": skipped,
                "errors": errors,
                "elapsed_ms": round(elapsed * 1000, 1),
                "total_records_now": len(self._by_id),
                "total_groups_now": len(self._groups),
            })

    def mark_ingestion_complete(self):
        """Call after all batches have been ingested."""
        with self._lock:
            self._ingestion_complete = True

    # ------------------------------------------------------------------
    # Internal parse
    # ------------------------------------------------------------------

    @staticmethod
    def _parse(raw: dict) -> ConditionRecord:
        """Extract structured fields from a raw FHIR Condition dict."""
        def extract_codes(raw_code: dict) -> tuple[list[str], list[str], bool]:
            snomed, icd10, is_admin = [], [], False
            for c in raw_code.get("coding", []):
                code   = c.get("code", "")
                system = c.get("system", "")
                if code in ADMIN_CODES:
                    is_admin = True
                if system == SNOMED_SYSTEM and code:
                    snomed.append(code)
                elif system == ICD10_SYSTEM and code and code not in ADMIN_CODES:
                    icd10.append(code)
            return list(dict.fromkeys(snomed)), list(dict.fromkeys(icd10)), is_admin

        code_block   = raw.get("code", {})
        display      = code_block.get("text", "")
        if not display and code_block.get("coding"):
            display = code_block["coding"][0].get("display", "")

        snomed_codes, icd10_codes, is_admin = extract_codes(code_block)

        status_block   = raw.get("clinicalStatus", {})
        status_codings = status_block.get("coding", [])
        if status_codings:
            status = status_codings[0].get("display", "unknown")
        else:
            status = status_block.get("text", "unknown")

        onset      = raw.get("onsetPeriod", {})
        identifiers = [i["value"] for i in raw.get("identifier", []) if "value" in i]
        recorder    = raw.get("recorder", {}).get("reference")

        return ConditionRecord(
            id=raw["id"],
            display_text=display,
            clinical_status=status,
            onset_start=onset.get("start"),
            onset_end=onset.get("end"),
            snomed_codes=snomed_codes,
            icd10_codes=icd10_codes,
            is_admin=is_admin,
            source_identifiers=identifiers,
            recorder_id=recorder,
            raw=raw,
        )

    def _upsert(self, rec: ConditionRecord):
        """Insert or update a record, maintaining the SNOMED group index."""
        with self._lock:
            self._by_id[rec.id] = rec

            if not rec.snomed_codes:
                # No SNOMED codes → isolated group keyed by record id
                gk = f"id:{rec.id}"
                if gk not in self._groups:
                    self._groups[gk] = ConceptGroup(snomed_codes=set())
                existing_ids = {r.id for r in self._groups[gk].records}
                if rec.id not in existing_ids:
                    self._groups[gk].records.append(rec)
                else:
                    self._groups[gk].records = [
                        r if r.id != rec.id else rec
                        for r in self._groups[gk].records
                    ]
                return

            # Find all existing groups this record bridges
            existing_gks: set[str] = {
                self._snomed_to_group[sc]
                for sc in rec.snomed_codes
                if sc in self._snomed_to_group
            }

            if not existing_gks:
                # Brand-new concept group
                gk = "|".join(sorted(rec.snomed_codes))
                grp = ConceptGroup(snomed_codes=set(rec.snomed_codes))
                grp.records.append(rec)
                self._groups[gk] = grp
                for sc in rec.snomed_codes:
                    self._snomed_to_group[sc] = gk

            elif len(existing_gks) == 1:
                # Add to existing group
                gk = next(iter(existing_gks))
                grp = self._groups[gk]
                existing_ids = {r.id for r in grp.records}
                if rec.id not in existing_ids:
                    grp.records.append(rec)
                else:
                    grp.records = [r if r.id != rec.id else rec for r in grp.records]
                # Expand group's known SNOMED codes
                new_codes = set(rec.snomed_codes) - grp.snomed_codes
                grp.snomed_codes.update(new_codes)
                for sc in new_codes:
                    self._snomed_to_group[sc] = gk

            else:
                # Record bridges multiple groups → merge them all into one
                merged_records: list[ConditionRecord] = []
                merged_snomed: set[str] = set(rec.snomed_codes)
                retracted = False
                for gk in existing_gks:
                    grp = self._groups.pop(gk)
                    merged_records.extend(grp.records)
                    merged_snomed.update(grp.snomed_codes)
                    retracted = retracted or grp.retracted
                existing_ids = {r.id for r in merged_records}
                if rec.id not in existing_ids:
                    merged_records.append(rec)
                new_gk = "|".join(sorted(merged_snomed))
                new_grp = ConceptGroup(snomed_codes=merged_snomed)
                new_grp.records  = merged_records
                new_grp.retracted = retracted
                self._groups[new_gk] = new_grp
                for sc in merged_snomed:
                    self._snomed_to_group[sc] = new_gk

    # ------------------------------------------------------------------
    # Correction
    # ------------------------------------------------------------------

    def retract_concept(self, concept_hint: str) -> dict:
        """
        Retract all groups matching the concept hint.

        Matches against:
          • Group display text (case-insensitive substring)
          • SNOMED codes (substring match, so "11999007" works)
          • ICD-10 codes of any record in the group

        Returns a summary dict with retracted_groups and retracted_record_ids.
        """
        hint_lower = concept_hint.lower()
        retracted_groups = []
        retracted_ids = []

        with self._lock:
            for gk, grp in self._groups.items():
                if grp.retracted:
                    continue
                display_match = hint_lower in grp.display.lower()
                code_match    = any(hint_lower in sc for sc in grp.snomed_codes)
                icd_match     = any(
                    hint_lower in icd
                    for r in grp.records
                    for icd in r.icd10_codes
                )
                if display_match or code_match or icd_match:
                    grp.retracted = True
                    retracted_groups.append(gk)
                    retracted_ids.extend(r.id for r in grp.records)

        return {
            "retracted_groups": len(retracted_groups),
            "retracted_record_ids": retracted_ids,
            "concept_hint": concept_hint,
        }

    # ------------------------------------------------------------------
    # Query  (the hot path)
    # ------------------------------------------------------------------

    def query(
        self,
        text: Optional[str] = None,
        include_admin: bool = False,
        include_retracted: bool = False,
        active_only: bool = False,
        limit: int = 50,
    ) -> dict:
        """
        Instant search over concept groups.

        Returns immediately regardless of ingestion state.
        `partial=True` means ingestion is not yet complete.
        """
        results = []
        with self._lock:
            for gk, grp in self._groups.items():
                if not include_retracted and grp.retracted:
                    continue
                c = grp.canonical
                if c is None:
                    continue
                if not include_admin and c.is_admin:
                    continue
                if active_only and not grp.active_records:
                    continue
                if text:
                    tl = text.lower()
                    if not (
                        tl in c.display_text.lower()
                        or any(tl in sc for sc in grp.snomed_codes)
                        or any(tl in icd for icd in c.icd10_codes)
                    ):
                        continue

                results.append({
                    "group_key": gk,
                    "display": grp.display,
                    "clinical_status": c.clinical_status,
                    "onset_start": c.onset_start,
                    "onset_end": c.onset_end,
                    "snomed_codes": sorted(grp.snomed_codes),
                    "icd10_codes": sorted({
                        icd for r in grp.records for icd in r.icd10_codes
                    }),
                    "record_count": len(grp.records),
                    "is_admin": c.is_admin,
                    "retracted": grp.retracted,
                })

        return {
            "results": results[:limit],
            "total_matching": len(results),
            "ingestion_complete": self._ingestion_complete,
            "total_ingested_records": len(self._by_id),
            "total_groups": len(self._groups),
            "partial": not self._ingestion_complete,
        }

    def status(self) -> dict:
        """Monitoring: full ingestion report and data quality summary."""
        with self._lock:
            return {
                "ingestion_complete": self._ingestion_complete,
                "total_records": len(self._by_id),
                "total_groups": len(self._groups),
                "retracted_groups": sum(
                    1 for g in self._groups.values() if g.retracted
                ),
                "admin_groups": sum(
                    1 for g in self._groups.values()
                    if g.canonical and g.canonical.is_admin
                ),
                "ingestion_log": self.ingestion_log,
            }