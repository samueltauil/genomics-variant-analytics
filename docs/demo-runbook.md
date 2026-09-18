# Demo runbook

> **Status: partial implementation.** This runbook is executable for the local
> metadata-only harnesses and preflight/reset checks. Azure provisioning,
> secondary analysis, governed analytics, and a full delivery remain
> subscription- or deployment-dependent. Do not present specified-only behavior
> as demonstrated.

Read [the claim register](claim-register.md), [the coverage table](coverage.md),
and the dated, unverified [cost statement](../README.md#cost) before any
delivery. A phase that does not produce its confirming observation stops at that
phase; use its diagnostic instead of continuing.

## Phase 0 — Preflight

**Expected duration:** 2–5 minutes locally; live Azure checks depend on CLI
latency and subscription permissions.

Run from the repository root:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File scripts\Test-DemoPreflight.ps1 |
  ConvertFrom-Json
```

For a deterministic local check, pass `-SnapshotPath` to a JSON snapshot with
`subscription`, `roles`, `quotas`, `regionalAvailability`, and `tooling`
objects. The deliberately unprepared fixture and the ready fixture are covered
by `tests\test_demo_preflight.py`; snapshot success is not live Azure evidence.

**Confirming observation:** `Ready: true`, every check is `PASS`, and the
validated region is named. The deployment entry point runs the same preflight
before reading the subscription or creating a resource.

**Diagnostic:** inspect every check's `Found` and `Required` values. A live
`UNVERIFIED` result is not readiness.

## Phase 1 — Bring-up

**Expected duration:** not locally verified. The existing foundation has a
previous disposable acceptance record, but the current subscription was not
re-queried and this repository does not claim a current ready environment.

With an approved, priced, isolated subscription and a passing live preflight,
run the single entry point:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File scripts\Deploy-Accelerator.ps1 `
  -SubscriptionId <subscription-id> -Location <region> -EnvironmentName <name>
```

**Required ready-state observations:** the deployment output records the
resource group and environment file; the landing share, ADLS taxonomy, private
connections, and staging identities pass their authorized acceptance checks;
the variant store is empty before seeding.

**Diagnostic:** stop on any missing observation. Review the preflight JSON, ARM
deployment output, private-endpoint approvals, and the environment record. Do
not infer readiness from a successful template submission.

## Phase 2 — Seeding

**Expected duration:** under 30 seconds for the metadata-only local harness;
cloud transfer duration is unverified.

```powershell
python scripts\stage_demo_landing.py `
  --manifest demo\dataset-manifest.json `
  --root <local-or-authorized-landing-root> `
  --inventory <inventory.sqlite3>
```

**Confirming observation:** the report is `verified: true`,
`paths_preserved: true`, contains 34 synthetic placeholder files, and every
inventory entry is `complete` with run/sample identifiers, size, arrival time,
and state. No genomic payload is created by this harness.

**Diagnostic:** rerun the focused stage test and inspect the first mismatched
relative path or modified placeholder. For a real share, use the authorized
landing scanner and do not treat local timings as SMB evidence.

## Phase 3 — Presentation sequence

The seven steps below name the output required by the capability contract and
state whether this repository currently produces it. Show only the evidence
listed as local or previously recorded; the remaining output is a production
consideration or specified-only behavior.

| Step | Observable output required | Current evidence |
|---|---|---|
| 1. Ingest | Unchanged instrument path, run/sample identifiers, file arrival, size, timestamp, and `arriving`/`complete`/`failed` state | **Local:** metadata-only layout, inventory, and manifest-declared failure and retry. **Previously recorded:** disposable storage acceptance. No instrument or SMB transfer was exercised. |
| 2. Stage | Source path, destination URI, transfer state, integrity result, storage tier, classification, and landing-to-object lineage | **Local:** staging log and checksum tests. Purview lineage and lifecycle tiering are not implemented. |
| 3. Process | QC → alignment → BAM/CRAM → variant calling → VCF/GVCF, workflow/reference/compute provenance, timings, outcome, and log | **Specified only:** no Nextflow, Batch/HPC run, or concordance result. |
| 4. Build variant store | Accepted/rejected counts, reference build, pipeline version, source links, rejected records, and maintenance state | **Local:** SQLite Bronze parser and rejection/provenance tests. It is not a deployed Delta store. |
| 5. Query | Gene, quality, cross-cohort, allele-in-sample, pipeline-version, and sequencing-run results with traceability | **Specified only:** no notebook, SQL endpoint, or governed query result. |
| 6. Visualize | Gene-centric, frequency, cohort, quality funnel, sample-to-file lineage, and processing-status views | **Specified only:** no dashboard or rendered view. |
| 7. Govern | Access-tier decisions, de-identification, source/reference/pipeline traceability, and reprocessing audit | **Local:** policy and hash-chained audit model. Azure identity, service boundary, and full lineage remain unverified. |

## Phase 4 — Rehearsed failures

**Expected duration:** 5–10 minutes for local negative tests; live delivery
timings are unverified.

| Demonstration | Local trigger | Expected response | Evidence status |
|---|---|---|---|
| Failed transfer | Write a synthetic run file shorter than the size its `{run_id}/transfer-manifest.json` declares, then run `scripts/scan_landing.py --transfer-manifest '{run_id}/transfer-manifest.json' --stall-seconds 5` twice | Mark `failed` with `incomplete-transfer`, withhold it from `available_for_staging`, and on re-send to the declared size return the same record to `arriving` then `complete` without disturbing siblings | **Local and tested.** Failure is declared against the manifest, not inferred from a stalled copy; see [failure detection and retry](landing-inventory.md#failure-detection-and-retry). |
| Rejected variant record | Ingest a synthetic VCF row missing `REF` or `ALT` with `scripts.variant_store.VariantStore` | Retain reason, source URI, line number, accepted/rejected counts; do not write the bad row | **Local and tested.** |
| Denied access | Use `scripts.governance.GovernancePolicy` without the required synthetic grant | Raise an explicit authorization error and append a denial audit entry; do not return an empty success | **Local and tested.** |

## Phase 5 — Reset

**Expected duration:** under 30 seconds for local SQLite delivery state; cloud
reset is not implemented.

Reset only the explicitly named local delivery stores, without redeploying
infrastructure:

```powershell
python scripts\reset_demo.py --state-root <local-state-root>
python scripts\reset_demo.py --state-root <local-state-root> --diagnose
```

The script removes only known SQLite files directly beneath the supplied state
root and leaves infrastructure and unrelated files untouched.

**Confirming observation:** the JSON report has `clean: true`,
`infrastructure_touched: false`, and no rows remain visible in the named
delivery stores. If reset is interrupted, run `--diagnose`; each store reports
its existence, table counts, and clean state. Do not begin another delivery
until every store is clean.

## Phase 6 — Teardown

**Expected duration:** unverified; Azure deletion and soft-delete retention
vary by subscription and resource.

After a separately authorized live delivery:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File scripts\Remove-Accelerator.ps1 `
  -EnvironmentName <name> -SubscriptionId <subscription-id>
```

The script refuses an untagged resource group and reports soft-deleted
survivors. **Required live observation:** the named resource group and every
demo-created resource are absent from the target subscription. This has not
been re-verified in the current change, so task 11.10 remains unchecked.

If teardown is deferred, the provisioned-v2 SSD share bills for provisioned
capacity/IOPS/throughput; a running verification VM, retained compute,
analytics capacity, or Managed Lustre can also accrue idle cost. The amount is
unverified; use the dated cost statement and a current pricing calculation.

## Talk track

Use two explicit labels while presenting:

- **Demonstrated here:** local preflight snapshot behavior, synthetic landing
  layout, manifest-declared transfer failure and retry, staging-log integrity
  decisions, variant rejection/provenance, local access-denial/audit behavior,
  and local reset diagnostics.
- **Production consideration or specified only:** live subscription readiness,
  Azure provisioning, interrupted transfers observed over SMB or from an
  instrument, secondary analysis, deployed Delta
  and analytics surfaces, Purview lineage, lifecycle transitions, live cost,
  and teardown cleanliness.

Say that this is an accelerator and reference architecture built from
validated patterns. Do not say it is a released Microsoft blueprint, supported
product, compliance outcome, confirmed customer deployment, clinical decision
system, diagnosis, or treatment recommendation. AI-assisted analysis is
exploratory. Review every delivery against [claim-register.md](claim-register.md)
and [coverage.md](coverage.md).

## Personas

| Persona | Lead with |
|---|---|
| Laboratory operations manager | Instrument compatibility, file arrival, and reruns |
| Bioinformatics engineer | Workflow portability, reference identity, and reproducibility |
| Research scientist | Queryable variants and cohort exploration |
| Clinical genomics team | Provenance, reference versions, quality filters, and auditability |
| Cloud or data architect | Storage boundaries, networking, identity, cost, and Batch versus HPC |
