# Local governance controls

This repository includes a SQLite-backed policy model in
`scripts/governance.py` for locally verifiable governance behavior. It is
development evidence for the accelerator, not a deployed identity boundary or
regulatory control.

## Access tiers and explicit denies

The four independent tiers are `raw_genomic_files`, `variant_store`,
`cohort_analytics`, and `synthetic_demo`. A grant is recorded per principal
and tier; a grant at a broader tier never implies access to a more restricted
tier. `authorize_raw_file` explicitly denies a FASTQ, BAM, or CRAM read unless
the principal has the raw-file tier. `read_cohort_aggregates` requires the
cohort-analytics tier, while `authorize_variant_store` requires the governed
variant-store tier. Denials raise `AuthorizationError` and are recorded as
`deny:<operation>` audit events rather than returning an empty success.

## De-identified projection

`GovernancePolicy.project_variant` authorizes the variant-store query, keeps
sample and cohort attributes, and removes `research_subject_id` unless the
separate `subject_linkage` capability is granted. This is a projection
decision, not a whole-query denial. Subject linkage is synthetic in all tests
and examples.

## Workspace movement

Research and clinical workspace grants are independent. A cross-workspace
transfer requires both workspace grants and a synthetic approval identifier.
Denied and approved attempts are recorded as `cross_workspace_transfer`
events. No direct database or cloud data movement is performed by this local
model.

## Classification

`scripts/stage_records.py` requires one of the fixed classification labels on
every staging record. The exact 20-field `variant_records` table is unchanged:
classification is recorded as run provenance and in the
`variant_classification` sidecar, then exposed through
`VariantStore.classification_for_run` and
`VariantStore.records_with_classification`. This avoids schema drift while
making classification available alongside variant rows to governed consumers.
No classification is inferred or fabricated.

## Append-only audit

The audit table records pipeline executions, data access, reprocessing, and
cross-workspace transfers with principal, operation, affected data, timestamp,
and a SHA-256 hash chained to the previous entry. SQLite triggers reject
updates and deletes, and `AuditTrail.verify()` checks the complete chain.
Metadata reads of clinical/patient-linked attributes and reprocessing events
are wired to this trail.

These checks run locally against synthetic SQLite data. Managed identities,
Key Vault secret retrieval, private endpoints, and service-side audit
retention remain deployment-dependent and are not claimed as locally verified
by this document.
