# Demo runbook

> **Draft — the demo is not built yet.** This is the shape the runbook will take, derived from the [`platform/demo-enablement`](../openspec/changes/add-genomics-variant-accelerator/specs/platform/demo-enablement/spec.md) spec. Steps carry no durations or commands yet because there is nothing to time or run. Do not attempt a delivery from this document.

For prerequisites, cost, and coverage, see the [README](../README.md). This document picks up once the environment is yours to provision.

## Before you start

- [ ] Read [docs/claim-register.md](claim-register.md). Every delivery depends on it.
- [ ] Check the coverage table in the [README](../README.md#coverage). Anything marked specified only is described, never demonstrated.
- [ ] Confirm preflight passed against the target subscription and region.

## Phase 1 — Bring-up

Provision the environment. Runs once per environment, not once per delivery.

Each step will state its expected duration and the observation that confirms it worked. If a step finishes without producing its confirming observation, go to that phase's diagnostic — not to the next step.

**Ready state:** landing zone reachable over SMB, staging pipeline deployed, reference data published, variant store created and empty, environments and approvals configured.

## Phase 2 — Seeding

Load the synthetic run into the landing zone under a realistic instrument folder convention.

**Confirming observation:** files visible in the landing zone with run and sample identifiers, sizes, arrival timestamps, and state `complete`.

## Phase 3 — Presentation

Seven steps. Each names the observable output its capability spec requires — show that output, not a slide of it.

### 1. Ingest

A synthetic sequencing run writes to the SMB share.

Show: existing folder convention, sample and run identifiers, file arrival, size and state, and that nothing on the instrument side changed.

**The point:** the laboratory changes nothing.

### 2. Stage

Files move from the file share into object storage.

Show: source, destination, transfer state, integrity result, storage tier, classification, lineage link.

### 3. Process

Launch the pipeline on Batch or HPC.

Show: `FASTQ → QC → alignment → BAM → variant calling → VCF`, plus workflow version, reference genome, compute pool, start and end time, outcome, log location.

**The point:** same workflow definition, two execution targets, identical outputs.

### 4. Build the variant store

Parse the VCF into Delta.

Show: variants ingested, reference build, pipeline version, source-file links, rejected records, table maintenance state.

### 5. Query

Notebook or SQL endpoint against the store.

Show: variants in a named gene, variants passing quality filters, variants across cohorts, samples carrying an allele, records from an older pipeline version, variants from a given run.

### 6. Visualize

Show: gene-centric view, variant frequency, cohort comparison, quality-filter funnel, sample-to-file lineage, processing status.

### 7. Govern

Show: who can read raw files, who can query de-identified variants, which source file produced a result, which reference build and pipeline version were used, how a reprocessing event is recorded.

**The point:** every result traces back to a file, a run, and a reference build.

## Phase 4 — Rehearsed failures

Do not improvise these. Each has a defined trigger and an expected response.

| Demonstration | Expected response |
|---|---|
| Interrupted transfer | File marked `failed`, excluded from staging, retryable without disturbing siblings |
| Malformed variant record | Rejected with reason and source line; counts reported; other records unaffected |
| Unauthorized access attempt | Explicit authorization error, not an empty result set |

Failure handling is usually more convincing than the happy path. Budget time for it.

## Phase 5 — Reset

Return to the Phase 2 starting state without redeploying infrastructure.

**Confirming observation:** no variant records, runs, or issues from the prior delivery are visible.

If a reset is interrupted, the diagnostic tells you which stores are clean and which are not. Do not start a delivery on a partially reset environment.

## Phase 6 — Teardown

Remove everything the demo created.

**Confirming observation:** no demo-created resource remains in the subscription.

Keeping the environment between deliveries is reasonable — but Azure Managed Lustre and provisioned-v2 SSD file shares bill while idle. The cost section of the README will carry the daily rate once it is measured.

## Talk track

Two rules:

**Separate demonstrated from asserted.** When you cover behavior the environment does not exercise, say so. "In production you would also..." is honest. Showing a slide and letting it read as running software is not.

**Stay inside the claim register.** No compliance claim, no released-blueprint claim, no unverified customer attribution, no clinical determination claim for assisted output.

## Personas

Tune emphasis to who is in the room.

| Persona | Leads with |
|---|---|
| Laboratory operations manager | Instrument compatibility, file arrival, failed transfers, reruns |
| Bioinformatics engineer | Pipeline portability, reference genomes, scaling, reproducibility |
| Research scientist | Queryable variants, cohorts, notebooks, cross-study comparison |
| Clinical genomics team | Provenance, reference versions, quality filters, auditability |
| Cloud or data architect | Storage tiers, networking, cost, identity, Batch versus HPC |
