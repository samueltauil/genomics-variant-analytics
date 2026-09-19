"""Governed end-to-end lineage over the local accelerator stores.

The resolver joins variant provenance, metadata-store artifact graphs, and
staging records. ``CatalogContext`` is deliberately an item-level Purview
catalog simulation: it supplies catalog labels and item context, but never
replaces record-level provenance or claims a live Purview connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from scripts.governance import AuthorizationError, synthetic_id
from scripts.metadata_store import MetadataStore
from scripts.stage_records import StagingLog
from scripts.variant_store import VariantStore


@dataclass(frozen=True)
class CatalogItemContext:
    item_id: str
    item_type: str
    uri: str
    display_name: str
    classifications: tuple[str, ...] = ()
    properties: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "item_type": self.item_type,
            "uri": self.uri,
            "display_name": self.display_name,
            "classifications": list(self.classifications),
            "properties": dict(self.properties),
        }


class CatalogContext:
    """Item-level catalog context with an explicit Purview simulation boundary."""

    provider = "Microsoft Purview"
    mode = "simulation"
    live = False

    def __init__(self):
        self._items_by_uri: dict[str, CatalogItemContext] = {}

    def register(
        self,
        item_id: str,
        item_type: str,
        uri: str,
        display_name: str,
        *,
        classifications: tuple[str, ...] = (),
        properties: Mapping[str, str] | None = None,
    ) -> CatalogItemContext:
        synthetic_id(item_id, "catalog item_id")
        if not all(isinstance(value, str) and value.strip()
                   for value in (item_type, uri, display_name)):
            raise ValueError("Catalog item type, URI and display name are required.")
        context = CatalogItemContext(
            item_id=item_id,
            item_type=item_type,
            uri=uri,
            display_name=display_name,
            classifications=tuple(classifications),
            properties=tuple(sorted((properties or {}).items())),
        )
        self._items_by_uri[uri] = context
        return context

    def for_uri(self, uri: str) -> dict[str, Any] | None:
        context = self._items_by_uri.get(uri)
        return context.as_dict() if context else None

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "mode": self.mode,
            "live": self.live,
            "item_count": len(self._items_by_uri),
            "scope": "item-level context only; record-level lineage remains local",
        }


class LineageResolver:
    """Resolve backward and forward lineage without exposing restricted identity."""

    def __init__(
        self,
        variant_store: VariantStore,
        metadata_store: MetadataStore,
        staging_log: StagingLog,
        catalog_context: CatalogContext | None = None,
    ):
        self.variant_store = variant_store
        self.metadata_store = metadata_store
        self.staging_log = staging_log
        self.catalog_context = catalog_context or CatalogContext()

    def _authorized(self, principal_id: str) -> tuple[bool, bool]:
        self.metadata_store.authorize_variant_store(principal_id)
        raw = self.metadata_store.governance.connection.execute(
            """SELECT 1 FROM governance_tier_grants
               WHERE principal_id = ? AND access_tier = 'raw_genomic_files'""",
            (principal_id,),
        ).fetchone() is not None
        subject = self.metadata_store.governance.connection.execute(
            """SELECT 1 FROM governance_capability_grants
               WHERE principal_id = ? AND capability = 'subject_linkage'""",
            (principal_id,),
        ).fetchone() is not None
        return raw, subject

    @staticmethod
    def _subject_visibility(trace: dict[str, Any], subject_visible: bool) -> dict[str, Any]:
        if subject_visible:
            return trace
        visible_ids = {
            entity["entity_id"] for entity in trace["entities"]
            if entity["kind"] != "subject"
        }
        return {
            **trace,
            "entities": [
                entity for entity in trace["entities"]
                if entity["entity_id"] in visible_ids
            ],
            "links": [
                link for link in trace["links"]
                if link["parent_id"] in visible_ids and link["child_id"] in visible_ids
            ],
        }

    def _metadata_chain(self, source_file_uri: str, subject_visible: bool) -> dict[str, Any]:
        artifact = self.metadata_store.find_artifact_by_uri(source_file_uri)
        trace = self.metadata_store.trace_artifact(artifact["entity_id"])
        return self._subject_visibility(trace, subject_visible)

    def backward_trace(self, principal_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
        """Trace an analytics result to VCF, run, staged artifact and landing file."""
        raw_visible, subject_visible = self._authorized(principal_id)
        required = ("source_file_uri", "pipeline_version")
        missing = [field for field in required if not result.get(field)]
        if missing:
            raise ValueError(f"Variant result is missing {', '.join(missing)}.")
        provenance_rows = self.variant_store.connection.execute(
            """SELECT * FROM run_provenance
               WHERE source_file_uri = ? AND pipeline_version = ?""",
            (result["source_file_uri"], result["pipeline_version"]),
        ).fetchall()
        if len(provenance_rows) != 1:
            raise ValueError("Variant result does not resolve to exactly one provenance run.")
        provenance = dict(provenance_rows[0])
        stage = self.staging_log.get_by_destination_uri(result["source_file_uri"])
        if stage is None or stage["state"] != "staged" or stage["integrity_result"] != "verified":
            raise ValueError("Variant source is not backed by a verified staging record.")
        pipeline_run = self.metadata_store.get_pipeline_run(provenance["run_id"])
        result_copy = dict(result)
        if not subject_visible:
            result_copy.pop("research_subject_id", None)
        return {
            "direction": "backward",
            "access": {
                "raw_content_readable": raw_visible,
                "subject_linkage_visible": subject_visible,
            },
            "variant_result": result_copy,
            "pipeline_run": {**provenance, **pipeline_run},
            "vcf_artifact": self.metadata_store.find_artifact_by_uri(result["source_file_uri"]),
            "staged_artifact": stage,
            "landing_file": {
                "source_path": stage["source_path"],
                "run_id": stage["run_id"],
                "sample_id": stage["sample_id"],
                "content_readable": raw_visible,
            },
            "metadata_chain": self._metadata_chain(result["source_file_uri"], subject_visible),
            "catalog_context": self.catalog_context.for_uri(result["source_file_uri"]),
            "catalog_status": self.catalog_context.status(),
        }

    def forward_trace(self, principal_id: str, source_path: str) -> dict[str, Any]:
        """Trace a landing file to verified staged artifacts and derived variants."""
        raw_visible, subject_visible = self._authorized(principal_id)
        stage = self.staging_log.get(source_path)
        if stage is None:
            raise ValueError("Unknown landing-zone file.")
        if stage["state"] != "staged" or stage["integrity_result"] != "verified":
            raise ValueError("Landing-zone file has no verified downstream artifact.")
        provenance_rows = self.variant_store.connection.execute(
            """SELECT * FROM run_provenance WHERE source_file_uri = ?
               ORDER BY pipeline_version""",
            (stage["destination_uri"],),
        ).fetchall()
        if not provenance_rows:
            raise ValueError("Landing file has no derived variant records.")
        runs = []
        for row in provenance_rows:
            provenance = dict(row)
            pipeline_run = self.metadata_store.get_pipeline_run(provenance["run_id"])
            variants = [
                variant for variant in self.variant_store.records(
                    source_file_uri=stage["destination_uri"]
                )
                if variant["pipeline_version"] == provenance["pipeline_version"]
            ]
            if not subject_visible:
                variants = [
                    {key: value for key, value in variant.items()
                     if key != "research_subject_id"}
                    for variant in variants
                ]
            runs.append({
                "pipeline_run": {**provenance, **pipeline_run},
                "vcf_artifact": self.metadata_store.find_artifact_by_uri(
                    provenance["source_file_uri"]
                ),
                "variant_records": variants,
                "metadata_chain": self._metadata_chain(
                    provenance["source_file_uri"], subject_visible
                ),
            })
        return {
            "direction": "forward",
            "access": {
                "raw_content_readable": raw_visible,
                "subject_linkage_visible": subject_visible,
            },
            "landing_file": {
                "source_path": stage["source_path"],
                "run_id": stage["run_id"],
                "sample_id": stage["sample_id"],
                "content_readable": raw_visible,
            },
            "staged_artifact": stage,
            "derived": runs,
            "catalog_context": self.catalog_context.for_uri(stage["destination_uri"]),
            "catalog_status": self.catalog_context.status(),
        }
