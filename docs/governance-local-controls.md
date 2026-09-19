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

## Reference publish and read

`reference_publisher` and `reference_reader` are independent grants; neither
implies the other. `GovernancePolicy.authorize_reference` records a
`reference_data` audit event for every authorization decision, naming the
principal, operation, outcome (`authorized` or `denied`), role, entry type,
entry name, immutable version, combined `type/name/version` identity, and UTC
timestamp. A principal without the grant gets an explicit `AuthorizationError`
and a `denied` outcome for the requested operation, so a refused publish is as
visible as an authorized one.

`ReferenceZone` routes `publish` through `reference_publisher` and
`get_manifest`, `get_manifest_bytes`, `manifests`, and `inventory` through
`reference_reader`. Authorization runs before the write path, so a denied
publish leaves the zone byte-for-byte unchanged. Workflow submission resolves
each explicitly requested immutable manifest through the same governed
`get_manifest_bytes` path before allocation, so those reads are attributed to
the submitting principal. Missing versions still fail with no default,
substitution, or allocation. The governor and principal are required
constructor arguments with no default: an unaudited zone must be asked for by
passing `None` for both, which keeps every unaudited call site visible.
The Azure client drivers in `scripts/Publish-Reference.ps1` and
`scripts/Test-ReferenceData.ps1` do exactly that, because those runs have no
durable audit store; routing the deployed publisher through a retained audit
trail is not implemented.

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

The audit table records pipeline executions, data access, reference publish and
read decisions, reprocessing, and
cross-workspace transfers with principal, operation, affected data, timestamp,
and a SHA-256 hash chained to the previous entry. SQLite triggers reject
updates and deletes, and `AuditTrail.verify()` checks the complete chain.
Metadata reads of clinical/patient-linked attributes and reprocessing events
are wired to this trail.

## Identity-based service access and secret handling

Every service-to-service path in the tracked infrastructure authenticates with
a managed identity rather than a key. `infra/modules/data-lake.bicep` and
`infra/modules/landing-zone.bicep` set `allowSharedKeyAccess: false` on both
storage accounts, so no shared key exists to embed. `infra/modules/staging.bicep`
gives the Data Factory `credentials` resources `type: 'ManagedIdentity'`
referencing the ingestion and staging user-assigned identities, and its
linked services reference those credentials rather than an account key or
connection string. `infra/modules/identities.bicep` defines the three
user-assigned identities; `infra/modules/test-client.bicep` attaches them to
the verification VM. The Python drivers (`scripts/stage_landing.py`,
`scripts/blob_transport.py`, `scripts/Test-Staging.ps1`,
`scripts/Test-StagingIntegrity.ps1`) obtain a bearer token from IMDS with the
target identity's client id and never read or embed a static key.

No component in this repository currently requires an external secret, so
there is nothing to place in Key Vault: the design is deliberately keyless
rather than key-vault-backed. If a future task introduces an external tool
that needs a credential, the governance access-and-lineage spec's
"External tool needs a secret" scenario requires it be retrieved from a
managed secret store at run time and never persisted in source or
configuration; no code path in this repository currently violates that,
because none reaches for a secret at all.

`scripts/scan_secrets.py` is a git-blob-level scanner, structured like
`scripts/check_data_hygiene.py`, that rejects Azure Storage/Cosmos/Service
Bus/Event Hub connection strings, bare 88-character storage/Cosmos account
keys, SAS query strings carrying both a signature and expiry, PEM private key
blocks, and literal `client_secret` assignments, while tolerating explicit
placeholder values (`changeme`, `***`, `REDACTED`, and similar). Fourteen
focused tests in `tests/test_scan_secrets.py` cover each detection category, a
clean repository, placeholder tolerance, and the CLI's failure modes. Running
it against this repository's current tree
(`python scripts/scan_secrets.py --repo .`) reports zero violations. The
scanner also runs as a second step in the existing required
`.github/workflows/data-hygiene.yml` job, so a pull request introducing an
embedded secret fails the same required check as a genomic-file violation.

These checks run locally against synthetic SQLite data, the repository's
tracked IaC and scripts, and the current working tree. They confirm the code
and infrastructure definitions are managed-identity-only with no embedded
connection string or storage key. They do not re-verify managed-identity
authentication against a live Azure environment: `rg-genomics-demo` is
absent, so this document does not claim a current deployment exercised these
paths. Private endpoints and service-side audit retention remain
deployment-dependent and are not claimed as locally verified by this
document.

## External sharing approval gate

`GovernancePolicy.grant_sharing_approval` records an explicit approval naming
the dataset, recipient, purpose, and an expiry, and the grant itself is
audited as an `external_sharing_approval` event. `share_externally` re-checks
a fresh approval row before every share attempt: the approval id, dataset,
recipient, and purpose must all match, the approval must not be expired, and
it must not have been used by an earlier share. Holding `variant_store` or
`cohort_analytics` read access never satisfies this check by itself, so a
principal with full query access is still denied a share with no matching
approval. A denied attempt and an approved share are both recorded as
`external_sharing` audit events (`deny:share_externally` and
`share_externally`), and a used approval is marked so it cannot be replayed
for a second share. As with every other audit event, these entries are
appended to the existing hash-chained, update/delete-blocked
`governance_audit` table, so approval grants and share decisions inherit the
same tamper-evidence as the rest of the trail.
