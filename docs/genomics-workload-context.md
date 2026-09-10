# Genomics Storage Workload Context

**Reviewed 2026-09-10. Status: sourced background and proposed test-design guidance, not benchmark results or new acceptance criteria.**

## Source and Scope

The supplied URL identifies the [SPECstorage Solution 2020 User's Guide, version 1.2](https://www.spec.org/storage2020/docs/usersguide.pdf#page=1), not the SPEC SFS 2014 SP2 guide named in the original link label. Page references below use the PDF's page numbers.

The guide's GENOMICS workload models storage I/O across a genomics workflow using synthesized, sanitized traces from commercial and research facilities. It does not run biological analysis or contain the original genome data. Its business metric is synthetic **JOBS**, not genomes processed or samples per hour. See [section 6.5.1, page 36](https://www.spec.org/storage2020/docs/usersguide.pdf#page=36).

Section 6 identifies the distribution's `storage2020.yml` as the definitive workload definition; the PDF is a summary, not enough to establish an exact reproduction. No SPEC software was installed or run for this review, and no official SPEC result is claimed.

## What the Model Describes

| Observation from the guide | Interpretation boundary |
|---|---|
| 70% sequential reads and 2% random reads; 8% sequential writes and 1% random writes | These are application-level operation counts, not byte fractions or cloud-billed IOPS. |
| 19% metadata operations: 12% stat, 4% access, and 1% each create, unlink and chmod | File-count and metadata pressure matter alongside bulk throughput. This is not an arrival-scanner profile. |
| 96% of read transfers are 128 KiB; 87% of write transfers are 512 KiB | These summarize the synthetic workload, not mandatory block sizes for our tools. |
| 81% of synthetic files are smaller than 128 KiB; the distribution also includes 100 MiB files | This is not a FASTQ/BAM size distribution or a whole-genome storage estimate. |
| Four processes per JOB, each requesting 250 operations/second | Nominally 1,000 requested application operations/second per JOB, not guaranteed achieved load or device IOPS. |
| 300-second warmup; configured compression and deduplication percentages are zero | Cache state and content characteristics affect interpretation; this does not imply durable-write guarantees. |

Sources: [operation definitions, page 10](https://www.spec.org/storage2020/docs/usersguide.pdf#page=10), [GENOMICS operations and parameters, page 37](https://www.spec.org/storage2020/docs/usersguide.pdf#page=37), and [transfer/file distributions, page 38](https://www.spec.org/storage2020/docs/usersguide.pdf#page=38).

The resource guidelines give approximately **3.5 GiB of target capacity and 416 MiB of load-client memory per GENOMICS JOB** ([section 2.3, page 11](https://www.spec.org/storage2020/docs/usersguide.pdf#page=11)). These are synthetic benchmark provisioning guidelines. They do not size alignment, variant calling, reference indexes, a genome, or a production sample. Client caching and filesystem/network behavior can split, combine or avoid backend operations; do not convert the requested operation count directly into storage-service IOPS or cost.

The guide assesses a whole solution under test, including load clients, network, file servers and backend storage. It reports load, achieved operations, throughput and response time; these are not isolated disk measurements. Average response time and the guide's Overall Response Time metric should not be relabeled as tail latency. See [measurement terminology, page 10](https://www.spec.org/storage2020/docs/usersguide.pdf#page=10) and [interpretation and cache coverage, page 39](https://www.spec.org/storage2020/docs/usersguide.pdf#page=39).

## Application to This Project

The following mapping is **project interpretation**, not SPEC's per-stage specification. An aggregate trace-derived model is a starting hypothesis; the selected Nextflow workflow and its individual stages must supply the eventual measurements.

| Project boundary | Proposed characterization | What it would not establish |
|---|---|---|
| Sequencer landing | Large sequential writes, read-back integrity, concurrent senders and inventory metadata overhead | Downstream processing performance or successful-transfer detection from stability alone |
| Object-storage staging | Copy throughput, checksum overhead and source/destination backpressure | Secondary-analysis runtime or a filesystem benchmark result |
| Secondary analysis and scratch | Concurrent reads, reference-cache reuse, intermediate writes, small-file operations and metadata latency | Biological correctness, exact SPEC equivalence or a universal executor preference |
| Delta variant analytics | Representative cohort queries, filters, joins, pruning and concurrent readers | Validation by the GENOMICS filesystem profile |

Downstream analysis continues to consume staged object-storage data, not the SMB landing share. Shared reference reads and scratch behavior belong to the processing boundary. The existing [landing specification](../openspec/changes/add-genomics-variant-accelerator/specs/ingestion/smb-landing-zone/spec.md) and [secondary-analysis specification](../openspec/changes/add-genomics-variant-accelerator/specs/processing/secondary-analysis/spec.md) remain authoritative.

### Future Independent Measurements

When a benchmark implementation and execution scope are separately approved:

- Record requested versus achieved load, concurrency, read/write throughput, metadata rates and latency together. Per-operation p95/p99 latency would be an additional project metric, not a substitute for SPEC's reported metrics.
- Record client CPU/RAM, filesystem and protocol, mount options, network, storage configuration, tool/workflow/reference versions and warmup/measurement durations.
- Describe file counts and size distributions, total working-set size, reference reuse, cold/warm cache state and data compressibility/deduplication assumptions. Use bounded synthetic fixtures locally; local runs cannot establish cloud acceptance.
- Calibrate the mixed-I/O hypothesis against stage-level traces from the actual authorized workflow. Keep scientific concordance, provenance coverage, end-to-end time and cost per real sample as separate evaluations.

These are candidate measurement dimensions, not new required thresholds, chosen infrastructure sizes, or authorization to collect sensitive traces.

## Existing Acceptance and Local Tool Limits

[Task 1.3](../openspec/changes/add-genomics-variant-accelerator/tasks.md) still requires the provisioned SMB share, a **100 GiB sequential write** sustaining provisioned throughput, and verification of the expected IOPS ceiling. The broader SPEC profile does not replace that ingestion acceptance test.

The existing [local write harness at development commit d89796e](https://github.com/samueltauil/genomics-variant-analytics/blob/d89796e/scripts/Test-LandingWrite.ps1) accepts at most 1 GiB and defaults to 16 MiB. It repeats one random buffer of up to 1 MiB, times sequential writes plus a flush, then verifies SHA-256 and cleanup. A small working set and repeated content can interact with caching and data reduction. Its timing is a smoke measurement, not representative genomics throughput, SMB acceptance, a durability certification, or verified provisioned IOPS.

SPEC's synthetic workload cannot validate variant correctness, Delta queries, access controls or lineage. Nothing in this note selects Fabric versus Databricks, Batch versus HPC, a region, an SKU, or a spending limit. No Azure access, provisioning, upload or benchmark execution is authorized by this context capture; those actions remain paused. No OpenSpec task is completed by adding this note.

## Reporting and Licensing

Official SPEC results follow applicable run/reporting rules and review. The guide distinguishes official workloads from modified user workloads and restricts comparison/publication of the latter; consult the applicable license and rules before running or publishing SPEC-derived tests. Independently authored project tests must be labeled as such, without suggesting official SPEC scores, certification or comparability. See [workload definitions, page 27](https://www.spec.org/storage2020/docs/usersguide.pdf#page=27) and [FAQ, pages 39-40](https://www.spec.org/storage2020/docs/usersguide.pdf#page=39).

The formal benchmark is not a default CI smoke test: the FAQ describes at least ten load points and roughly 30-90 minutes per point ([page 40](https://www.spec.org/storage2020/docs/usersguide.pdf#page=40)). This note summarizes selected facts; it does not redistribute the benchmark, its complete workload definition, or the guide.