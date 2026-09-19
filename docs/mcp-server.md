# Governed MCP-style server facade

`scripts/mcp_server.py` implements task 10.8 of the
`add-genomics-variant-accelerator` change: a minimal, standards-aligned
MCP-style server that fronts the existing governed query interface
(`AnalyticsQueryEngine`, `AnalyticsViewModels`, `AssistedCohortExploration`)
and `GovernancePolicy`. It adds no new data access path; every tool
delegates to those existing, already-governed surfaces.

## Scope and limitations

- This is a **local, in-process facade** over runtime-generated synthetic
  data. **No deployed network endpoint exists**: `serve_stdio` reads JSON
  request objects from a stdio stream and writes JSON response objects back;
  it opens no port and starts no network listener. Standing up a
  network-reachable, authenticated MCP endpoint remains a deployment
  consideration this module does not address.
- It is a demo solution-accelerator facade built from validated patterns,
  not a released Microsoft product, supported offering, or confirmed
  end-to-end customer deployment.

## Tool catalog

`MCPServer.list_tools()` returns three tools, none of which names a table,
file path, connection string, or storage credential:

- `ask_cohort_question(principal_id, question)` — bounded, gene-scoped
  natural-language cohort exploration via `AssistedCohortExploration.ask`.
  Every response is labelled exploratory (not diagnostic) and carries
  per-row traceability (`source_file_uri`, `producing_run`,
  `reference_build`, `pipeline_version`).
- `gene_centric_view(principal_id, gene)` — the governed gene-centric view.
- `variant_frequency_view(principal_id)` — the governed variant-frequency view.

## Access-tier enforcement

`MCPServer.call_tool` authorizes the caller against the `variant_store`
access tier *before* dispatching to any tool — a server-side, defense-in-depth
check at the MCP boundary, in addition to the identical enforcement already
inside the delegated engine/view/exploration methods. A caller without the
tier grant is denied with `MCPToolError`, and the denial is recorded in the
governance audit trail by `GovernancePolicy.authorize`.

A caller without the `subject_linkage` capability never receives
`research_subject_id`, regardless of how the natural-language question is
phrased: the principal is passed through unchanged to the governed query
core, so rephrasing a question cannot widen access.

## Audit trail

Every `ask_cohort_question` call appends an `ai_assisted_cohort_exploration`
audit event (via `AssistedCohortExploration.ask`) in addition to the
`read_variant_store` authorization event recorded by the mandatory tier
check above, whether the call is authorized or denied.

## Running the server

In-process (recommended for tests — no subprocess, no real stdio):

```python
from scripts.mcp_server import MCPServer
from scripts.analytics_query import AnalyticsQueryEngine

engine = AnalyticsQueryEngine(variant_store, metadata_store)
server = MCPServer(engine)
tools = server.list_tools()
response = server.call_tool(
    "ask_cohort_question",
    {"principal_id": "SYN-ANALYST-001", "question": "Tell me about gene GENE1."},
)
```

Over stdio, for local interactive or scripted use against on-disk SQLite
stores:

```powershell
python -m scripts.mcp_server <variant_store.sqlite3> <metadata_store.sqlite3>
```

Each line of standard input is a JSON request object:

```json
{"id": 1, "method": "tools/list"}
{"id": 2, "method": "tools/call", "params": {"name": "ask_cohort_question", "arguments": {"principal_id": "SYN-ANALYST-001", "question": "Tell me about gene GENE1."}}}
```

Each line of standard output is the matching JSON response object
(`{"id": ..., "result": ...}` or `{"id": ..., "error": ...}`).

## Tests

`tests/test_mcp_server.py` verifies, against runtime-generated synthetic
data only:

- Tool enumeration lists the expected tools and no schema contains
  credential-shaped text.
- An unauthorized caller is denied and the denial is audited.
- Rephrasing an assisted question does not widen access: subject linkage
  stays withheld for a de-identified caller across multiple phrasings.
- Every assisted result row carries full traceability.
- Every assisted response carries the exploratory notice.
- Every assisted query appends an audit event.
- No server or engine attribute carries credential-shaped text.
- A stdio JSON-Lines round trip (`tools/list` then `tools/call`) works
  in-process via `io.StringIO`, without a real process or socket.
