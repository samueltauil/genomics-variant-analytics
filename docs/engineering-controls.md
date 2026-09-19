# Engineering review, failure triage, and account-tier controls

These controls support a demo solution accelerator and reference architecture.
They do not create a support commitment or make a deployment compliant.

## Secretless deployment and protected releases

`.github/workflows/deploy-protected.yml` and
`.github/workflows/pipeline-container.yml` request only the GitHub OIDC
`id-token` permission and use `azure/login` with repository variables for the
federated application, tenant, and subscription identifiers. They do not read
Azure client secrets, storage keys, or connection strings. The workflows fail
closed when the required variables, resource group, or ACR settings are
missing; they do not provision Azure resources.

The `clinical` and `research` environments must be configured in GitHub with
required reviewers, `prevent_self_review: true`, administrator bypass disabled,
and a deployment branch policy that permits only `v*` tags. The workflow also
refuses non-tag refs. Environment configuration is live repository metadata and
is not created by a clone; the acceptance record below states what was actually
configured.

## Container provenance and SBOM

`containers/pipeline/Dockerfile` is a metadata-only synthetic accelerator image;
the toolchain labels are placeholders, not evidence of a production
bioinformatics toolchain. The container workflow builds a release tag, pushes it to the ACR named by
repository variables, and publishes both SLSA provenance and CycloneDX SBOM
attestations to that registry using `push-to-registry: true`. The generated
SBOM is augmented with the reviewed synthetic toolchain declaration so the
aligner and variant-caller versions are explicit rather than inferred from
copied scripts.

`scripts/supply_chain.py` is the pre-allocation gate. It requires a digest,
repository/commit/workflow provenance, an SBOM containing `aligner` and
`variant-caller`, and a full commit SHA for every declared dependency. The
pipeline submission path calls it before the allocator; optional registry
verification runs `gh attestation verify` for both provenance and SBOM
predicates. No fallback to an unattested image is allowed.

### Task 10 live acceptance record — 2026-09-19

The repository is public. Live GitHub API inspection found no repository
secrets. `clinical` and `research` now exist with administrator bypass disabled,
required reviewer `samueltauil`, self-review prevention enabled, and a `v*`
deployment tag policy. Because the only available reviewer is also the
authenticated actor, this configuration intentionally cannot produce a
self-approved deployment; an independent reviewer must be added before a
successful approved deployment can be claimed.

The workflow and local gates are implemented and tested. Immutable releases
are enabled live, and `v0.1.0-pipeline` was published from a draft at commit
`febafa0cc78777da8ae046253051c0b4aec83e41` with the pipeline manifest,
reference compatibility manifest, toolchain metadata, and checksums. GitHub
reports the release as immutable; `gh release verify` retrieved and verified
the release attestation, and force-move/delete probes for the tag were
rejected. Tag-name reuse after deleting an immutable release was not exercised
because the verified release is retained. A disposable immutable release
probe was separately deleted and an attempt to recreate its tag name was
rejected.

The live foundation includes an admin-disabled ACR and a managed identity with
an `AcrPush` grant. `Configure-GitHubOidc.ps1` reads GitHub's repository OIDC
subject configuration, including the immutable owner/repository identifiers,
and configures environment-scoped Entra credentials for `release-build`,
`clinical`, and `research`.

Release `v0.2.1-pipeline` is immutable at commit
`05c832b79140965f5de1d420476765bed2e9bbff`. Workflow run `35468110327`
authenticated to Azure through OIDC and pushed the image to
`acrgentgrxjnw6usjfg.azurecr.io`. Registry-backed `gh attestation verify`
validated the SLSA provenance and CycloneDX predicates for image digest
`sha256:c05f74d757061a5e9f07b6c86653b7a8d5b98e0e6d842fbb860510b64606483d`.
The signed SBOM names `synthetic-aligner-1.0.0` and
`synthetic-variant-caller-1.0.0`. Repository and environment secret
enumeration returned no Azure credential. Independent approval and a
successful protected `clinical` or `research` deployment remain unverified.

## Automated pull-request review

`.github/workflows/engineering-review.yml` runs trusted default-branch code on
pull requests that touch workflow definitions, container definitions,
`workflows/reference-compatibility.json`, the implemented variant schema, or
the governed variant-store spec. It checks proposed commits as Git objects and
does not execute pull-request code.

The review fails when:

- a workflow's reference sets change without changing its `workflow_version`;
- `scripts/variant_store.py` declares a `VARIANT_FIELDS` column absent from the
  exact schema statements in the Delta variant-store spec;
- the implementation omits a specified column, duplicates a column, or either
  schema source cannot be parsed.

Run it locally with:

```text
python -I scripts/review_engineering_changes.py --base origin/main --head HEAD
```

The current governed row remains exactly the eight VCF core fields `CHROM`,
`POS`, `ID`, `REF`, `ALT`, `QUAL`, `FILTER`, `INFO` and the twelve context
fields `sample_id`, `research_subject_id`, `cohort_id`, `gene`, `transcript`,
`variant_consequence`, `genotype`, `allele_frequency`, `reference_build`,
`pipeline_version`, `source_file_uri`, `ingestion_timestamp`. Schema changes
must update the OpenSpec contract in the same reviewed change. Reference
version or manifest digest remains run provenance; it is not a new variant
column.

## Scheduled failure triage

`.github/workflows/pipeline-failure-triage.yml` runs daily at 06:17 UTC and may
also be dispatched manually. It consumes a downloaded
`pipeline-failures.json` artifact. The upstream pipeline must emit a JSON array
whose entries contain:

- `failing_stage`
- `run_id`
- `reference_build`
- `pipeline_version`
- `log_location`
- optional stable `failure_key`, `occurrence_id`, and `occurred_at`

`scripts/triage_pipeline_failures.py` uses a hidden stable failure marker to
open one issue per failure key. A new occurrence updates and reopens that
issue; replaying the same occurrence is a no-op. Issue bodies carry only
operational provenance and explicitly prohibit genomic data, patient
identifiers, credentials, and copied log content.

Dry-run without GitHub access:

```text
python -I scripts/triage_pipeline_failures.py --input failures.json --dry-run
```

The dry-run adapter and GitHub issue adapter share the same triage logic.
Automated tests prove create, recurrence-update, idempotency, and required
provenance behavior.

### Live triage acceptance record — 2026-09-19

A manually invoked synthetic acceptance run exercised the same GitHub issue
adapter called by the scheduled workflow. The first occurrence created
disposable issue #26 with failing stage `variant-calling`, synthetic run
identifier `SYN-RUN-TRIAGE-20260919`, reference build `GRCh38` with assembly
version `GCA_000001405.15`, pipeline version
`v0.1.0-synthetic-triage`, and an `example.invalid` log location. A second,
distinct occurrence returned action `update` for the same issue number.

The acceptance query found exactly one issue carrying the stable failure
marker. Its body contained both occurrence markers and `Recurrence count: 2`.
Issue #26 was then closed as disposable test evidence. This demonstrates the
live GitHub create/update path without leaving an open test issue. The
06:17 UTC cron configuration is repository evidence; this acceptance invoked
the triage path manually rather than waiting for the next scheduled trigger.

## Account tier, visibility, substitutes, and residual gaps

Account and product terms can change. Re-check the target account immediately
before configuring these controls.

| Feature | Dependency | Substitute when unavailable | Residual gap |
|---|---|---|---|
| Push rulesets for forbidden file types, paths, and sizes across a fork network | The platform contract assumes this control targets private or internal repositories; organization-wide rulesets also require an eligible organization tier. | In this public personal-account repository, protect the default branch, require pull requests, and require the trusted `data-hygiene` merge check. | Content can still be pushed to an unprotected branch or fork and may become public before merge review. The filename/size scanner does not classify arbitrary PHI or archive contents. |
| Required deployment reviewers, prevention of self-review, disabled administrator bypass, and release-tag deployment restrictions | Environment protection availability depends on repository visibility and GitHub plan; the design assumes public repositories make these protections available to the personal-account demo. | Refuse protected deployment in workflow code unless the ref is an immutable release tag; use a separate manually controlled Azure identity and record the approver outside GitHub. | Workflow checks cannot reproduce GitHub's pre-job secret withholding or prove independent approval. A manual record is weaker and easier to bypass. |
| Organization-wide branch or tag policy | Requires an eligible organization plan and organization ownership. | Configure equivalent repository-level branch/ruleset settings on every fork and record acceptance evidence per repository. | Settings can drift between repositories and there is no central enforcement or inventory. |
| Copilot content exclusion, centrally managed Copilot policy, and Copilot audit logs | Require Copilot Business or Enterprise organization capabilities; they are unavailable to the assumed personal-account deployment. | Keep genomic and patient data out of Git, enforce the merge-time data-hygiene gate, and expose variant data only through a governed query interface. | There is no equivalent assistant-side exclusion or central policy/audit control. Prompts may still include data supplied outside the repository; users must not do so. |
| Copilot code review and scheduled agent automation | Require the corresponding Copilot entitlement and feature availability for the account/repository. | Use the repository-owned `engineering-review.yml` and `pipeline-failure-triage.yml` workflows with deterministic Python checks and GitHub's issue API. | The substitute is rule-based, not semantic agent review. Scheduled execution still depends on Actions being enabled, and inactive repositories or platform outages can delay runs. |
| GitHub-hosted Actions capacity | Public repositories use the public-repository Actions allowance; private-repository minutes and runner access depend on plan and policy. | Run the same dependency-free Python commands on a governed self-hosted runner or an external CI service. | The substitute adds runner hardening, availability, patching, network, and cost responsibilities. |
| Secret scanning and push protection | Availability and coverage depend on visibility, plan, organization policy, and supported secret patterns. | Keep secretless OIDC deployment, scan in CI, and require managed secret stores for external-tool credentials. | CI detects after push and pattern scanners cannot detect every credential; provider bypass paths and unsupported formats remain. |
| Immutable releases and artifact attestations | Must be enabled and supported for the target repository and account; attestation availability and retention vary by plan/visibility. | Pin source commit and image digest in a signed external release record and verify it before allocation. | This is not the repository-native immutable tag/release guarantee and introduces external signer and record custody. The live public-repository acceptance does not prove availability for a different account tier. |
| Release assets for reference data | Each release asset is limited to the platform's per-file size ceiling; reference genomes can exceed it. | Store reference data in governed object storage and attach only the versioned manifest and checksums to the release. | Reproducibility depends on object-store retention, authorization, and URI durability in addition to the release. |

Repository workflows are configuration artifacts, not proof that required
checks, schedules, permissions, environments, or Copilot entitlements are
enabled on a fork. Administrators must configure and verify those settings.
