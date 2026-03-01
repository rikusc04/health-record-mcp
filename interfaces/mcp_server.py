# ---------------------------------------------------------------------------
# FastMCP server + tools
# ---------------------------------------------------------------------------

from conditions.store import ConditionStore
from fastmcp import FastMCP
from tools.tools import (
    query_conditions as query_conditions_implementation,
    correct_condition as correct_condition_implementation,
    store_status as store_status_implementation,
)

def create_mcp_server(store: ConditionStore) -> FastMCP:
    mcp = FastMCP("conditions-store")

    @mcp.tool()
    def query_conditions(text: str = "", active_only: bool = False, include_admin: bool = False, limit: int = 20) -> dict:
        """
        Search the live conditions store. Designed for RAG use: returns immediately with the best available data, even if background ingestion is still running.  Check `partial` in the response to know whether all data has been loaded.

        Args:
            text:              Free-text filter.  Matches display name, SNOMED code, or ICD-10 code.  Empty string returns all conditions
            active_only:       Only return groups with at least one Active record
            include_admin:     Include administrative/placeholder entries (default: False)
            limit:             Max concept groups to return (default 20)

        Returns:
            {
                results: [...],            # list of concept group summaries
                total_matching: int,       # total groups matching filter
                ingestion_complete: bool,
                total_ingested_records: int,
                total_groups: int,
                partial: bool,             # True if ingestion is not yet complete
            }
        """
        return query_conditions_implementation(
            store,
            text=text,
            active_only=active_only,
            include_admin=include_admin,
            limit=limit,
        )

    @mcp.tool()
    def correct_condition(concept: str) -> dict:
        """
        Retract all conditions matching a concept from the live store. Use this when the user says they do not have a condition, or that a record was entered in error.

        Args:
            concept: Name or code to retract.
            Examples:
                    - "tuberculosis"  (matches all TB-related groups)
                    - "Z22.7"         (ICD-10 code)
                    - "11999007"      (SNOMED code)

        Returns:
            {
                retracted_groups: int,
                retracted_record_ids: [str, ...],
                concept_hint: str,
                status_after: { ... },               # store_status() snapshot
            }

        The retraction is applied immediately and persists for the lifetime of the store.  Future query_conditions calls will exclude retracted concepts unless include_retracted=True is explicitly passed to the store's query() method.
        """
        return correct_condition_implementation(store, concept)


    @mcp.tool()
    def store_status() -> dict:
        """
        Return ingestion progress and data quality summary.

        Returns:
            {
                ingestion_complete: bool,
                total_records: int,
                total_groups: int,
                retracted_groups: int,
                admin_groups: int,
                ingestion_log: [ { batch, 
                                   timestamp, 
                                   added, 
                                   skipped, 
                                   errors,
                                   elapsed_ms, 
                                   total_records_now, 
                                   total_groups_now 
                                } ]
            }
        """
        return store_status_implementation(store)

    return mcp
