"""
Lotus Conditions Data Store + FastMCP Tools
============================================
Live, deduplicated representation of FHIR Condition resources with two MCP tools:
  • query_conditions  – RAG-style retrieval (returns immediately, even mid-ingestion)
  • correct_condition – user correction to retract a concept
  • store_status      – monitoring / ingestion progress

Usage
-----
    # Run the two-day ingestion simulation:
    python conditions_store.py conditions.json

    # Or import and use directly:
    from conditions_store import STORE, tool_query_conditions, tool_correct_condition
    STORE.ingest_batch(records, "day1")
    tool_query_conditions(text="tuberculosis")
    tool_correct_condition(concept="tuberculosis")

Architecture
------------
ConditionStore
  ├── _by_id:           dict[condition_id → ConditionRecord]     O(1) lookup
  ├── _snomed_to_group: dict[snomed_code → group_key]            inverted index
  └── _groups:          dict[group_key → ConceptGroup]           concept-level view

ConceptGroup
  - Aggregates all ConditionRecords sharing at least one SNOMED code.
  - "Canonical" record = the one with the most source identifiers
    (reconciled records in this dataset accumulate identifiers across systems).
  - `retracted` flag: set by user correction; excluded from queries by default.

Data quality handling
---------------------
Issue seen in dataset          → How we handle it
─────────────────────────────────────────────────
Vague/overlapping time ranges  → Stored as-is; query returns both onset_start/end
Wrong active/inactive status   → clinicalStatus respected; missing → "unknown"
Admin/clerical entries         → is_admin=True; excluded from queries by default
                                  (detected by ADMIN CODE or IMO0002 in coding)
Duplicate concepts             → Merged into one ConceptGroup via SNOMED index
"""

from __future__ import annotations

import json
import sys

from conditions.store import ConditionStore
from interfaces.mcp_server import create_mcp_server


# --------------------------------------------------
# Simulation
# --------------------------------------------------

def run_simulation(store: ConditionStore, data: list[dict]):

    import math

    mid  = math.ceil(len(data) / 2)
    day1 = data[:mid]
    day2 = data[mid:]

    sep = "=" * 70
    print(sep)
    print("LOTUS CONDITIONS DATA ENGINEERING — SIMULATION")
    print(sep)

    print(f"\nDAY 1: Ingesting {len(day1)} records...")
    store.ingest_batch(day1, batch_label="day1")

    log = store.ingestion_log[-1]
    print(f"   ✓ Added: {log['added']}")

    print("\nQUERY (mid-ingestion):")
    r = store.query(limit=5)

    print("\nQUERY 'tuberculosis':")
    tb = store.query(text="tuberculosis")

    print(f"\nDAY 2: Ingesting {len(day2)} records...")
    store.ingest_batch(day2, batch_label="day2")
    store.mark_ingestion_complete()

    print("\nUSER CORRECTION")
    store.retract_concept("tuberculosis")

    print("\nFINAL STATUS")
    print(store.status())


# --------------------------------------------------
# Entrypoint
# --------------------------------------------------

if __name__ == "__main__":

    mode      = sys.argv[1] if len(sys.argv) > 1 else "simulate"
    data_file = sys.argv[2] if len(sys.argv) > 2 else None

    # Create store ONCE
    store = ConditionStore()

    if mode == "simulate":

        import pathlib as _pl

        if data_file:
            data = json.loads(_pl.Path(data_file).read_text())
        else:
            print("Reading JSON from stdin...")
            data = json.load(sys.stdin)

        run_simulation(store, data)

    elif mode == "serve":

        if data_file:
            import math, pathlib as _pl

            print(f"Pre-loading {data_file}...", flush=True)

            data = json.loads(_pl.Path(data_file).read_text())

            mid = math.ceil(len(data) / 2)

            store.ingest_batch(data[:mid], "day1")
            store.ingest_batch(data[mid:], "day2")
            store.mark_ingestion_complete()

        mcp = create_mcp_server(store)

        print("Starting MCP server (stdio)...", file=sys.stderr, flush=True)

        mcp.run()

    else:
        print(f"Unknown mode '{mode}'. Use: simulate | serve")
        sys.exit(1)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# To run as an MCP server after pre-loading the dataset:
#
#   python -m app.main serve data/conditions.json
#
# To just run the simulation demo:
#
#   python -m app.main simulate data/conditions.json
# 
# To run it as a chat directly in your terminal:
# 
#   python -m chat.chat
# ---------------------------------------------------------------------------