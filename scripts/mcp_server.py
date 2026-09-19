"""Minimal, standards-aligned MCP-style server fronting the governed query interface.

This module is a local, in-process facade for tasks 9.1-9.7's governed
analytics surfaces (``AnalyticsQueryEngine``, ``AnalyticsViewModels``,
``AssistedCohortExploration``) and ``GovernancePolicy`` (task 10.8 of the
genomics-variant-accelerator change). It exposes a small, versionable tool
catalog and a JSON request/response protocol modeled on the Model Context
Protocol's ``tools/list`` and ``tools/call`` shape, over a stdio transport
suitable for both interactive use and in-process tests.

Scope and limitations
----------------------
- This is a demo solution-accelerator facade over local, runtime-generated
  synthetic data. It is not a deployed, network-reachable MCP endpoint, and
  it does not implement authentication, TLS, or a hosted service; a
  deployment would still need those addressed independently.
- No tool schema, response payload, or server attribute carries a raw table
  name, file path, connection string, SAS token, account key, or any other
  storage credential. Every tool call is dispatched through the existing
  governed engine/view/exploration surfaces, which only ever return
  de-identified, access-tier-projected rows.
- Every dispatched tool call is authorized against the caller's
  ``variant_store`` access tier before any row is read, both here (a
  server-side, defense-in-depth check at the MCP boundary) and again inside
  the delegated engine/view method. A denial is recorded in the governance
  audit trail rather than silently ignored.
- Assisted natural-language cohort questions are additionally recorded as a
  distinct ``ai_assisted_cohort_exploration`` audit event by
  ``AssistedCohortExploration.ask`` on every call, whether the call is
  authorized or a caller rephrases the question. Rephrasing a question can
  never grant subject linkage: the caller principal is passed through
  unchanged to the governed query core, so a caller without the
  ``subject_linkage`` capability never receives ``research_subject_id``.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import IO, Any, Mapping

from scripts.analytics_experience import AnalyticsViewModels, AssistedCohortExploration
from scripts.analytics_query import AnalyticsQueryEngine
from scripts.governance import AuthorizationError
from scripts.metadata_store import MetadataStore
from scripts.variant_store import VariantStore


class MCPToolError(RuntimeError):
    """Raised for an unknown tool, malformed arguments, or a denied caller."""


@dataclass(frozen=True)
class MCPTool:
    """A tool descriptor exposed to callers. Carries no credential material."""

    name: str
    description: str
    input_schema: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
        }


def _tool_definitions() -> tuple[MCPTool, ...]:
    principal_property = {"principal_id": {"type": "string"}}
    return (
        MCPTool(
            name="ask_cohort_question",
            description=(
                "Ask a bounded, gene-scoped cohort question through the governed "
                "AI-assisted exploration surface. The server enforces the "
                "caller's variant-store access tier before dispatch and "
                "labels every response as exploratory, not diagnostic."
            ),
            input_schema={
                "type": "object",
                "properties": {**principal_property, "question": {"type": "string"}},
                "required": ["principal_id", "question"],
                "additionalProperties": False,
            },
        ),
        MCPTool(
            name="gene_centric_view",
            description="Render the governed gene-centric analytics view for a gene.",
            input_schema={
                "type": "object",
                "properties": {**principal_property, "gene": {"type": "string"}},
                "required": ["principal_id", "gene"],
                "additionalProperties": False,
            },
        ),
        MCPTool(
            name="variant_frequency_view",
            description="Render the governed variant-frequency analytics view.",
            input_schema={
                "type": "object",
                "properties": dict(principal_property),
                "required": ["principal_id"],
                "additionalProperties": False,
            },
        ),
    )


class MCPServer:
    """In-process MCP-style facade over the governed query interface.

    Holds no raw table name, file path, connection string, or storage
    credential; every tool delegates to ``AnalyticsQueryEngine``,
    ``AnalyticsViewModels``, or ``AssistedCohortExploration``, all of which
    read exclusively through ``GovernancePolicy``.
    """

    def __init__(self, engine: AnalyticsQueryEngine):
        self.engine = engine
        self.views = AnalyticsViewModels(engine)
        self.exploration = AssistedCohortExploration(engine)
        self._tools: dict[str, MCPTool] = {tool.name: tool for tool in _tool_definitions()}

    def list_tools(self) -> tuple[MCPTool, ...]:
        """Return the tool catalog. No entry references a table, file, or credential."""
        return tuple(self._tools.values())

    def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Dispatch a governed tool call after mandatory server-side tier enforcement."""
        if tool_name not in self._tools:
            raise MCPToolError(f"Unknown tool: {tool_name}")
        principal_id = arguments.get("principal_id")
        if not isinstance(principal_id, str) or not principal_id.strip():
            raise MCPToolError("principal_id is required.")

        # Mandatory server-side access-tier enforcement at the MCP boundary,
        # independent of and in addition to the enforcement already inside
        # the delegated engine/view/exploration methods below. A denial is
        # audited by GovernancePolicy.authorize before the error is raised.
        try:
            self.engine.governance.authorize_variant_store(principal_id)
        except AuthorizationError as exc:
            raise MCPToolError(str(exc)) from exc

        if tool_name == "ask_cohort_question":
            question = arguments.get("question")
            if not isinstance(question, str) or not question.strip():
                raise MCPToolError("question is required.")
            try:
                response = self.exploration.ask(principal_id, question)
            except ValueError as exc:
                raise MCPToolError(str(exc)) from exc
            return {
                "governed_scenario": response.governed_scenario,
                "results": list(response.results),
                "traceability": list(response.traceability),
                "exploratory_notice": response.exploratory_notice,
            }
        if tool_name == "gene_centric_view":
            gene = arguments.get("gene")
            if not isinstance(gene, str) or not gene.strip():
                raise MCPToolError("gene is required.")
            return self.views.gene_centric(principal_id, gene)
        if tool_name == "variant_frequency_view":
            return self.views.variant_frequency(principal_id)
        raise MCPToolError(f"Unhandled tool: {tool_name}")  # pragma: no cover - exhaustive above


def _write_message(stream: IO[str], payload: Mapping[str, Any]) -> None:
    stream.write(json.dumps(payload, default=str) + "\n")
    stream.flush()


def serve_stdio(server: MCPServer, input_stream: IO[str] | None = None,
                 output_stream: IO[str] | None = None) -> None:
    """Serve JSON-Lines ``tools/list``/``tools/call`` requests over stdio.

    Reads one JSON request object per line from ``input_stream`` (default
    ``sys.stdin``) and writes one JSON response object per line to
    ``output_stream`` (default ``sys.stdout``). This is a local stdio
    transport, not a deployed network endpoint: no port is opened and no
    network listener is started by this function.
    """
    input_stream = sys.stdin if input_stream is None else input_stream
    output_stream = sys.stdout if output_stream is None else output_stream
    for raw_line in input_stream:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _write_message(output_stream, {"id": None, "error": f"Malformed JSON request: {exc}"})
            continue
        request_id = request.get("id")
        method = request.get("method")
        try:
            if method == "tools/list":
                result: Any = [tool.to_dict() for tool in server.list_tools()]
            elif method == "tools/call":
                params = request.get("params") or {}
                result = server.call_tool(params.get("name"), params.get("arguments") or {})
            else:
                raise MCPToolError(f"Unsupported method: {method}")
            _write_message(output_stream, {"id": request_id, "result": result})
        except MCPToolError as exc:
            _write_message(output_stream, {"id": request_id, "error": str(exc)})


def build_server(variant_store_path: str, metadata_store_path: str) -> MCPServer:
    """Construct an ``MCPServer`` over on-disk SQLite variant/metadata stores."""
    variant_store = VariantStore(variant_store_path)
    metadata_store = MetadataStore(metadata_store_path)
    engine = AnalyticsQueryEngine(variant_store, metadata_store)
    return MCPServer(engine)


def main(argv: list[str] | None = None) -> None:
    """Run the stdio server: ``python -m scripts.mcp_server <variant_db> <metadata_db>``."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(
            "usage: python -m scripts.mcp_server <variant_store.sqlite3> <metadata_store.sqlite3>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    server = build_server(argv[0], argv[1])
    serve_stdio(server)


if __name__ == "__main__":
    main()
