# health-record-mcp
This is a MCP-compatible health record retrieval system built on FHIR Conditions. This project implements a structured clinical condition store with semantic querying, deduplication, and tooling designed for RAG pipelines and MCP.


## Overview
- `health-record-mcp` provides:
    - Structured ingestion of FHIR Condition resources
    - Deduplicated concept grouping using SNOMED codes
    - Fast and queryable clinical record index
    - Non-blocking queries that return partial results during ingestion
    - MCP tool server exposing health record operations
    - Agent-compatible retrieval layer
- The system is designed as a backend infrastructure component for AI agents interacting with clinical data


## Architecture
ConditionStore (Domain Layer)
├── Record ingestion
├── Concept grouping + deduplication
├── Query interface
└── Retraction support

Tools Layer
├── query_conditions
├── correct_condition
└── store_status

Interfaces
└── MCP server (FastMCP)

Clients
├── MCP-compatible agents
└── Local CLI chat interface


## Concept Model
- A ConceptGroup aggregates all ConditionRecord instances that share at least one SNOMED code
- Each group:
    - Selects a canonical record (the record with the most source identifiers)
    - Maintains concept-level deduplication across systems
    - Supports user-driven retraction to exclude incorrect concepts from queries
- This enables consistent retrieval even when multiple EMR systems contain overlapping or reconciled records


## Features
- RAG-friendly structured retrieval
- Non-blocking querying data ingestion
- Thread-safe data store
- Concept-level deduplication
- MCP tool integration


## Data Quality Handling
- Real-world clinical datasets often contain inconsistencies
- This system explicitly handles:
    - Vague or overlapping onset ranges: preserved as-is
    - Missing or inconsistent clinical status: defaults to "unknown"
    - Administrative placeholder entries: excluded from queries by default
    - Duplicate concepts across systems: merged via SNOMED-based grouping


## Running the Project
1. To run the simulation demo:
    `python -m app.main simulate data/conditions.json`
    - Simulates multi-batch ingestion and querying
2. To run as an MCP server:
    `python -m app.main serve data/conditions.json`
    - Starts an MCP Server exposing:
        - `query_conditions`
        - `correct_condition`
        - `store_status`
3. To run it as a chat directly in your terminal:
    `python -m chat.chat`
    - An interactive CLI agent that uses the MCP Server tools


## Project Structure
app/            # Entry point / runtime modes
conditions/     # Domain models + store logic
interfaces/     # MCP server integration
tools/          # Tool implementations
chat/           # Agent CLI interface
data/           # Example dataset


## Design Goals
- Treat clinical data as structured domain entities rather than raw text
- Provide agent-friendly retrieval interfaces
- Separate domain logic from transport layers (MCP)
- Enable scalable health data tooling


## Technologies
- Python
- FHIR data model
- FastMCP


## Why MCP?
Model Context Protocol (MCP) enables standardized tool interaction between agents and external systems. This project demonstrates using MCP to expose structured clinical data as agent tools.


## Notes
- Please note that the FHIR data used in this repository is **NOT** real patient data
- To use the CLI chat with Claude, please use your own API Key. Create a `.env` file in the project root containing `ANTHROPIC_API_KEY={insert_your_api_key_here}`
- The project uses `python-dotenv` to load environment variables automatically.