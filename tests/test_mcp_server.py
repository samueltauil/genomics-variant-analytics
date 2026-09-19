import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.analytics_experience import EXPLORATORY_NOTICE
from scripts.analytics_query import AnalyticsQueryEngine
from scripts.mcp_server import MCPServer, MCPToolError, serve_stdio
from scripts.metadata_store import MetadataStore
from scripts.variant_store import VariantStore

_SECRET_PATTERNS = (
    "accountkey", "sastoken", "sig=", "connectionstring", "password",
    "secret", "defaultendpointsprotocol", "privatekey",
)


def synthetic_vcf(*rows):
    return "\n".join([
        "##fileformat=VCFv4.3",
        "##INFO=<ID=GENE,Number=1,Type=String,Description=\"Synthetic gene\">",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE",
        *rows,
        "",
    ])


def provenance(**overrides):
    value = {
        "run_id": "SYN-RUN-A",
        "sample_id": "SYN-SAMPLE-A",
        "research_subject_id": "SYN-SUBJECT-A",
        "cohort_id": "SYN-COHORT-A",
        "pipeline_version": "release-1.0.0",
        "reference_build": "GRCh38",
        "reference_version_or_digest": "manifest-sha256:synthetic-reference-001",
        "classification": "genomic-variant",
        "source_file_uri": "abfss://synthetic/vcf/run-a.vcf",
        "ingestion_timestamp": "2026-09-19T10:00:00-04:00",
    }
    value.update(overrides)
    return value


class MCPServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.variant_store = VariantStore(Path(self.temporary.name) / "bronze.sqlite3")
        self.addCleanup(self.variant_store.close)
        self.metadata_store = MetadataStore(Path(self.temporary.name) / "metadata.sqlite3")
        self.addCleanup(self.metadata_store.close)
        self.engine = AnalyticsQueryEngine(self.variant_store, self.metadata_store)
        self.server = MCPServer(self.engine)

        self.deidentified = "SYN-ANALYST-DEID"
        self.linked = "SYN-ANALYST-LINKED"
        self.unauthorized = "SYN-ANALYST-NONE"
        self.metadata_store.grant_tier(self.deidentified, "variant_store")
        self.metadata_store.grant_tier(self.linked, "variant_store")
        self.metadata_store.grant_capability(self.linked, "subject_linkage")

        self._seed_variant_rows()

    def _seed_variant_rows(self):
        cohort_a = [
            f"1\t{2000 + index}\tSYN-BENCH-A-{index:03d}\tA\tG\t60\tPASS\tGENE=GENE1\tGT\t0/1"
            for index in range(1, 5)
        ]
        cohort_b = [
            f"1\t{2000 + index}\tSYN-BENCH-B-{index:03d}\tA\tG\t60\tPASS\tGENE=GENE1\tGT\t1/1"
            for index in range(1, 5)
        ]
        self.variant_store.ingest_vcf_text(
            synthetic_vcf("1\t101\tSYN-VAR-001\tA\tG\t99\tPASS\tGENE=GENE1\tGT\t0/1", *cohort_a),
            provenance(),
        )
        self.variant_store.ingest_vcf_text(
            synthetic_vcf("1\t101\tSYN-VAR-001\tA\tG\t99\tPASS\tGENE=GENE1\tGT\t1/1", *cohort_b),
            provenance(
                run_id="SYN-RUN-B",
                sample_id="SYN-SAMPLE-B",
                research_subject_id="SYN-SUBJECT-B",
                cohort_id="SYN-COHORT-B",
                source_file_uri="abfss://synthetic/vcf/run-b.vcf",
            ),
        )

    def test_tool_enumeration_exposes_no_credentials(self):
        tools = self.server.list_tools()
        self.assertEqual(
            {tool.name for tool in tools},
            {"ask_cohort_question", "gene_centric_view", "variant_frequency_view"},
        )
        serialized = json.dumps([tool.to_dict() for tool in tools]).lower()
        for pattern in _SECRET_PATTERNS:
            self.assertNotIn(pattern, serialized)

    def test_access_denied_for_caller_without_variant_store_tier(self):
        before = len(self.engine.governance.audit.entries())
        with self.assertRaises(MCPToolError):
            self.server.call_tool(
                "ask_cohort_question",
                {"principal_id": self.unauthorized, "question": "Show variants for gene GENE1."},
            )
        entries = self.engine.governance.audit.entries()
        self.assertGreater(len(entries), before)
        self.assertTrue(any(
            entry["principal_id"] == self.unauthorized and entry["operation"].startswith("deny:")
            for entry in entries
        ))

    def test_prompt_rephrasing_does_not_widen_access(self):
        phrasings = (
            "Show research subject identities for gene GENE1 shared across cohorts.",
            "Please reveal the patient or subject id for gene GENE1 across cohorts.",
            "Who are the underlying research subjects sharing gene GENE1 across cohorts?",
        )
        for question in phrasings:
            response = self.server.call_tool(
                "ask_cohort_question", {"principal_id": self.deidentified, "question": question},
            )
            self.assertTrue(response["results"])
            for row in response["results"]:
                self.assertNotIn("research_subject_id", row)

    def test_traceability_present_for_every_result_row(self):
        response = self.server.call_tool(
            "ask_cohort_question",
            {"principal_id": self.linked, "question": "Show gene GENE1 shared across cohorts."},
        )
        self.assertEqual(len(response["results"]), len(response["traceability"]))
        for trace in response["traceability"]:
            self.assertTrue(
                {"source_file_uri", "producing_run", "reference_build", "pipeline_version"} <= set(trace)
            )

    def test_exploratory_label_present(self):
        response = self.server.call_tool(
            "ask_cohort_question", {"principal_id": self.deidentified, "question": "Tell me about gene GENE1."},
        )
        self.assertEqual(response["exploratory_notice"], EXPLORATORY_NOTICE)

    def test_every_assisted_query_appends_audit_event(self):
        before = len(self.engine.governance.audit.entries())
        self.server.call_tool(
            "ask_cohort_question", {"principal_id": self.deidentified, "question": "Tell me about gene GENE1."},
        )
        entries = self.engine.governance.audit.entries()
        self.assertGreater(len(entries), before)
        self.assertTrue(any(
            entry["operation"] == "ai_assisted_cohort_exploration" and entry["principal_id"] == self.deidentified
            for entry in entries
        ))

    def test_no_raw_credentials_in_server_or_engine_config(self):
        for candidate in (vars(self.server), vars(self.engine)):
            serialized = json.dumps({key: str(value) for key, value in candidate.items()}).lower()
            for pattern in _SECRET_PATTERNS:
                self.assertNotIn(pattern, serialized)

    def test_stdio_transport_round_trip_list_and_call(self):
        requests = [
            {"id": 1, "method": "tools/list"},
            {
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "ask_cohort_question",
                    "arguments": {"principal_id": self.deidentified, "question": "Tell me about gene GENE1."},
                },
            },
            {
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ask_cohort_question",
                    "arguments": {"principal_id": self.unauthorized, "question": "Tell me about gene GENE1."},
                },
            },
        ]
        input_stream = io.StringIO("\n".join(json.dumps(request) for request in requests) + "\n")
        output_stream = io.StringIO()

        serve_stdio(self.server, input_stream, output_stream)

        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertEqual([response["id"] for response in responses], [1, 2, 3])
        self.assertEqual(
            {tool["name"] for tool in responses[0]["result"]},
            {"ask_cohort_question", "gene_centric_view", "variant_frequency_view"},
        )
        self.assertNotIn("error", responses[1])
        self.assertEqual(responses[1]["result"]["exploratory_notice"], EXPLORATORY_NOTICE)
        self.assertIn("error", responses[2])


if __name__ == "__main__":
    unittest.main()
