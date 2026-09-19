# Demo runbook

> **Status: partial implementation.** This runbook is executable for the local
> metadata-only, secondary-analysis, governance and analytics harnesses plus
> preflight/reset checks. Azure provisioning, Batch/HPC execution, deployed
> analytics services and a full delivery remain subscription- or
> deployment-dependent. Do not present local evidence as live Azure behavior.

Read [the claim register](claim-register.md), [the coverage table](coverage.md),
and the dated [foundation cost estimate](cost-estimate.md) before any delivery.
A phase that does not produce its confirming observation stops at that phase;
use its diagnostic instead of continuing.

## Phase 0 — Preflight

**Expected duration:** 2–5 minutes locally; live Azure checks depend on CLI
latency and subscription permissions.

Run from the repository root:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File scripts\Test-DemoPreflight.ps1 |
  ConvertFrom-Json
```

This exact command runs in `local-preflight` mode: it checks only tooling and
repository files, never Azure, so it always reports `Ready: false` with
`BlockingFailures: 0` and nine `UNVERIFIED` checks (`azure-subscription` plus
one per required component's regional availability). That is the correct,
expected result of running the shown snippet unmodified -- it is not a
blocker to diagnose, and it is not evidence that Phase 1 can start.

For a deterministic local check that can reach `Ready: true`, pass
`-SnapshotPath` to a JSON snapshot with `subscription`, `roles`, `quotas`,
`regionalAvailability`, and `tooling` objects. The deliberately unprepared
fixture and the ready fixture are covered by `tests\test_demo_preflight.py`;
snapshot success is not live Azure evidence. Against a live subscription, add
`-RequireAzureChecks -SubscriptionId <subscription-id> -DeployerObjectId
<object-id>` instead; only that mode or a passing snapshot can report
`Ready: true`.

**Confirming observation:** in snapshot mode or live-Azure mode, `Ready: true`,
every check is `PASS`, and the validated region is named. In local mode (the
plain command above), the confirming observation is instead `Mode:
local-preflight`, `BlockingFailures: 0`, and every `UNVERIFIED` check naming
`azure-subscription` or a `regional-availability:*` component. The deployment
entry point runs the same preflight before reading the subscription or
creating a resource.

**Diagnostic:** inspect every check's `Found` and `Required` values. A `FAIL`
status is a real blocker. An `UNVERIFIED` status in local mode is the
expected result, not readiness evidence for Phase 1; it only becomes a gap to
chase down once you add `-SnapshotPath` or `-RequireAzureChecks` and it is
still `UNVERIFIED` or `FAIL`.

## Phase 1 — Bring-up

**Expected duration:** about 6 minutes for the first foundation deployment and
about 4 minutes for an immediate re-run in the authorized `eastus2`
subscription on September 19, 2026. The disposable resource group
`rg-genomics-20260919` exists with expiry October 3, 2026. Its identity,
network, landing storage, object storage, private endpoint, Data Factory,
verification-client, and Storage Actions task deployments report `Succeeded`.
The verification VM is deallocated. This is foundation readiness only, not an
end-to-end demo environment.

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
| 2. Stage | Source path, destination URI, transfer state, integrity result, storage tier, classification, and landing-to-object lineage | **Local:** staging log and checksum tests. **Live partial:** the Storage Actions task definition and identity are deployed, but no lifecycle transition ran because the private HNS account rejects the available Storage Actions access path. Purview lineage is not implemented. |
| 3. Process | QC → alignment → BAM/CRAM → variant calling → VCF/GVCF, workflow/reference/compute provenance, timings, outcome, and log | **Local:** pure-Python and real Nextflow runs on synthetic data, including success, failure-stage provenance and published outputs. **Unverified:** Azure Batch, Slurm/HPC, concordance and compute release. |
| 4. Build variant store | Accepted/rejected counts, reference build, pipeline version, source links, rejected records, and maintenance state | **Local:** SQLite Bronze parser and rejection/provenance tests. It is not a deployed Delta store. |
| 5. Query | Gene, quality, cross-cohort, allele-in-sample, pipeline-version, and sequencing-run results with traceability | **Local:** governed SQLite query engine, notebook-style session, SQL adapter, snapshots and traceability. No deployed notebook or SQL warehouse endpoint. |
| 6. Visualize | Gene-centric, frequency, cohort, quality funnel, sample-to-file lineage, and processing-status views | **Local:** six access-aware view models render on synthetic data. No deployed dashboard or rendered Azure view. |
| 7. Govern | Access-tier decisions, de-identification, source/reference/pipeline traceability, and reprocessing audit | **Local:** grants, de-identification, classification, reference authorization, external-sharing approval and hash-chained audit. Purview is simulated and Azure enforcement remains unverified. |

## Phase 4 — Rehearsed failures

**Expected duration:** under 10 seconds for the local rehearsal wrapper; live
delivery timings are unverified.

Run all three demonstrations from one entry point against the same local
state root used elsewhere in this runbook:

```powershell
python scripts\rehearse_demo_failures.py --state-root <local-state-root>
```

This writes to `landing_inventory.sqlite3`, `variant_store.sqlite3`,
`metadata_store.sqlite3`, `run_history.sqlite3`, and one explicitly named
synthetic landing directory (`rehearsal-landing`) directly under the state
root -- the same names `scripts/reset_demo.py` resets. No infrastructure,
credential, or genomic payload is touched.

| Demonstration | Local trigger | Expected response | Evidence status |
|---|---|---|---|
| Failed transfer | Write a synthetic run file shorter than the size its `{run_id}/transfer-manifest.json` declares, post an authoritative `{run_id}/transfer-failed.json` failure marker naming it, then scan twice with `scripts/scan_landing.py --transfer-manifest ... --failure-marker ...` | Mark `failed` with the marker's stated reason (for example `sender-aborted`), withhold it from `available_for_staging`, and on re-send to the declared size return the same record to `arriving` then `complete` without disturbing siblings | **Local and tested.** Failure is declared only from the authoritative marker, never inferred from a stalled copy; see [failure detection and retry](landing-inventory.md#failure-detection-and-retry). |
| Rejected variant record | Ingest a synthetic VCF row missing `REF` or `ALT` with `scripts.variant_store.VariantStore` | Retain reason, source URI, line number, accepted/rejected counts; do not write the bad row | **Local and tested.** |
| Denied access | Use `scripts.governance.GovernancePolicy` without the required synthetic grant | Raise an explicit authorization error and append a denial audit entry; do not return an empty success | **Local and tested.** |

**Confirming observation:** the harness JSON report has `all_passed: true`;
each demonstration's `actual_response` equals its `expected_response`, and
`infrastructure_touched` is `false`.

**Diagnostic:** a demonstration with `passed: false` names which expected
field its actual response did not match; inspect that demonstration's local
store directly (for example `scripts.variant_store.VariantStore.rejected_records`)
before assuming the underlying capability regressed.

## Phase 5 — Reset

**Expected duration:** under 30 seconds for local SQLite delivery state; cloud
reset is not implemented.

Reset only the explicitly named local delivery stores and the one explicitly
named local delivery directory (`rehearsal-landing`), without redeploying
infrastructure:

```powershell
python scripts\reset_demo.py --state-root <local-state-root>
python scripts\reset_demo.py --state-root <local-state-root> --diagnose
```

The script removes only the named SQLite files and the named directory
directly beneath the supplied state root; it never globs, never scans the
root for other content, and leaves infrastructure and unrelated files or
directories untouched (see `tests/test_reset_demo.py`).

**Confirming observation:** the JSON report has `clean: true`,
`infrastructure_touched: false`, and no rows remain visible in the named
delivery stores or files in the named directory. Reset is idempotent: running
it again once already clean removes nothing further and still reports
`clean: true`.

**Diagnostic:** if reset is interrupted partway (for example the process is
killed after some stores are removed but before others), run `--diagnose`.
Each store and directory reports its own `exists` and `clean` state
independently, so a partially completed reset is distinguishable from either
a fully clean or a fully dirty state root. Re-running the plain reset command
finishes only the stores and directory still present; it does not error on
ones already removed. Do not begin another delivery until every store and
directory reports `clean: true`.

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
demo-created resource are absent from the target subscription. This has been
verified once, live: task 11.10 is checked in
[tasks.md](../openspec/changes/add-genomics-variant-accelerator/tasks.md) on
the strength of a live teardown of `rg-genomics-demo` and a read-only
subsequent scan that found no resource group and no resource tagged
`project=genomics-variant-accelerator`. That is evidence for the disposable
run it was taken against, not a standing guarantee for a later delivery;
re-verify it after every teardown rather than relying on this record.

If teardown is deferred, the current Bicep default incurs a modeled minimum of
**$0.601/day** for the configured share and retained OS disk. A verification VM left
running adds **$6.360/day** before its disk and other usage; retained compute,
analytics capacity, Managed Lustre, private endpoints, payload storage, and
operations can add more. Use the dated [foundation cost estimate](cost-estimate.md)
and a fresh pricing calculation before approving an extended idle period.

## First-reader dry run

`scripts/dry_run_first_reader.py` plays a reader who has cloned the
repository and follows only this runbook and the scripts it links to, with no
other context. It runs Phases 0, 2, 4, and 5 exactly as documented above
against a scratch directory, compares each result to the confirming
observation this runbook promises, and reports Phases 1 and 6 as
`live-cloud` -- not executable without an authorized subscription id that no
published document supplies, rather than skipped silently:

```powershell
python scripts\dry_run_first_reader.py --scratch-root <scratch-dir> --write-report <report.json>
```

Any mismatch between a documented promise and the observed result is printed
as a documentation gap naming the exact phase, so it can be fixed here rather
than discovered by a presenter mid-delivery. The dated
[2026-09-19 dry-run evidence](dry-run-evidence-2026-09-19.json) is a run of
this harness: every locally executable phase matched its documented
observation with no undocumented input, and no gap remained open. See
`tests/test_dry_run_first_reader.py`.

## Talk track

Use two explicit labels while presenting:

- **Demonstrated here:** local preflight snapshot behavior, synthetic landing
  layout, manifest-declared transfer failure and retry, staging-log integrity
  decisions, variant rejection/provenance, local access-denial/audit behavior,
  and local reset diagnostics.
- **Production consideration or specified only:** acceptance of the fresh Azure
  deployment, interrupted transfers observed over SMB or from an
  instrument, deployed Delta and analytics surfaces, live Purview lineage,
  lifecycle transitions, live ACR attestations, live Batch/HPC execution, live cost,
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
