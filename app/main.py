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