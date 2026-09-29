# Secondary-analysis pipeline (local/containerized, Azure Batch, and Slurm)

This page documents the portable Nextflow secondary-analysis pipeline
delivered for tasks 5.1, 5.2, 5.5, and 5.6 of the secondary-analysis
processing spec
(`openspec/changes/add-genomics-variant-accelerator/specs/processing/secondary-analysis/spec.md`).
It is a demo solution accelerator artifact, not a Microsoft product, released
blueprint, or regulatory solution, and it makes no claim of biological
validation or compliance. See [claim-register.md](claim-register.md) and
[limitations.md](limitations.md) for the accelerator's positioning limits.

## Scope delivered

- **Task 5.1 -- author the pipeline.** `workflows/main.nf` is a real Nextflow
  DSL2 workflow with five processes: `GENERATE_DEMO_SAMPLE`,
  `QUALITY_CONTROL`, `ALIGN_READS`, `CALL_VARIANTS`, `PUBLISH_RESULTS`. It
  produces quality-control metrics, a sorted/indexed BAM (or CRAM) alignment,
  and a VCF (or GVCF) of called variants. `scripts/secondary_pipeline.py`
  implements the same stage logic as a pure-Python, dependency-light core
  used both by the Nextflow `bin/` wrapper scripts and by a standalone CLI
  (`scripts/run_secondary_pipeline.py`) that needs no Nextflow installation.
  Every run declares `reference_build` (`SYN-demo-genome`), immutable
  `reference_version` (`synthetic-1385e2e921c4`), and the canonical SHA-256 of
  `workflows/synthetic-reference-manifest.json`; there is no default,
  inference from contig names, or silent substitution. Both launchers reject a
  missing or incompatible declaration before starting pipeline compute, and
  the generator verifies the runtime FASTA against the metadata-only manifest.
- **Task 5.5 -- persist run provenance.** `scripts/pipeline_provenance.py`
  defines and validates thirteen provenance content fields (workflow id and
  version, reference build, version and manifest digest, execution target and
  compute pool, input URIs, output URIs, start and end time, terminal state,
  and log location), plus a `failing_stage` field that is required on failure and
  forbidden on success. The spec text says "verify all ten fields are
  present" but its own field list literally enumerates twelve distinct
  values; this implementation records all twelve named spec values plus the
  immutable manifest digest required by the reference-data contract rather than
  silently dropping two to match the word "ten" -- see
  [Known discrepancy](#known-discrepancy-in-the-spec-text) below.
- **Task 5.6 -- stage-level failure handling.** Any of the three stages
  (`quality_control`, `alignment`, `variant_calling`) can be forced to fail
  for testing (`--force-fail-stage`/`--force_fail_stage`). On failure, the
  provenance record identifies the exact failing stage, `output_uris` is
  empty, and nothing is copied into the publish directory -- confirmed both
  at the pure-Python orchestrator level and via real `nextflow run`
  executions (see [Manual verification evidence](#manual-verification-evidence)).

Task 5.3 now has a locally and statically validated single-campaign
orchestration path, but its required live create/use/copy-out/teardown
acceptance remains incomplete. The private-image implementation now configures
a private no-public-IP Trusted Launch Ubuntu 24.04 build VM, verifies its pinned
kernel and Secure Boot state, deprovisions/generalizes it, captures it into a
Gen2 `TrustedLaunchSupported` Compute Gallery definition, and validates the
retained version on a separate Trusted Launch VM. It uses the Microsoft
prebuilt signed AMLFS kmod package; it never installs DKMS, Docker, creates a
build storage account, or changes a VM security profile after provisioning.
Azure VM Image Builder was rejected on September 29, 2026 because its internal
staging storage account requires shared-key VHD access, which is incompatible
with the tenant policy requiring `allowSharedKeyAccess:false`. Focused tests
and Bicep compilation pass, but the Trusted Launch VM capture path has not yet
been live-validated. No validated gallery image exists. The earlier September
27 DKMS attempt remains historical failed evidence and is not the current
design. Task 5.4 (Batch-vs-HPC concordance) also remains outside this
implementation. Task 5.2 (Azure Batch live execution) is complete -- see
[Azure Batch profile -- validated with a live run](#azure-batch-profile----validated-with-a-live-run-task-52)
below.

## Two execution paths, one core

| Path | Entry point | Requires |
|---|---|---|
| Pure-Python orchestrator | `scripts/run_secondary_pipeline.py` | Python only (CI-safe; samtools optional) |
| Nextflow workflow | `workflows/main.nf` via `scripts/run_nextflow_secondary_pipeline.py` | A real `nextflow` binary |

Both paths call the same stage functions
(`scripts/secondary_pipeline.py::run_quality_control/run_alignment/run_variant_calling`)
and the same provenance schema (`scripts/pipeline_provenance.py`), so the
Nextflow workflow is a genuine, portable workflow-engine wrapper around the
tested pipeline logic rather than a separate, divergent implementation.

`scripts/run_nextflow_secondary_pipeline.py` runs `nextflow run` as a
subprocess, then persists provenance itself: it inspects the process exit
code and, on failure, greps `.nextflow.log` for
`Error executing process > '<PROCESS_NAME>'` to identify the failing stage.
This external-wrapper design was adopted after Nextflow's own
`workflow.onComplete` hook proved unusable for this purpose in the installed
Nextflow release (26.04.6): registering `onComplete` at the top level of the
script is rejected by the DSL2 parser ("statements cannot be mixed with
script declarations"), and registering it from inside the main `workflow {}`
block compiles but throws a `NullPointerException` at runtime because
`params`/`workflow` resolve to `null` inside that nested closure. This is
recorded as a environment-specific Nextflow limitation, not a design choice.

## Reference build and version

Every runnable submission requires `--reference_build`/`--reference-build`,
`--reference_version`/`--reference-version`, and
`--reference_manifest_sha256`/`--reference-manifest-sha256`; there is no
default. The demo reference is a 120bp synthetic sequence (not a real genome)
with two deliberately injected SNP positions used only so the naive variant
caller below has a known answer to check itself against.

The exact identity is:

- Build: `SYN-demo-genome`
- Version: `synthetic-1385e2e921c4`
- Canonical manifest SHA-256:
  `7e3be36672095e4018dfded5466ddb002848387e19d314595cb1a128a231be83`
- Runtime-generated `reference.fasta` SHA-256:
  `51a195ba91b85581e581cc9d039f234df29dae83da01e44a6b0527780350c6da`

`workflows/synthetic-reference-manifest.json` stores only this identity,
generation provenance, checksum, and byte count. The FASTA is generated at
runtime with normalized LF bytes and is never committed. Any content change
changes the checksum and requires a new immutable version and manifest digest.

## Naive stub logic -- explicitly not validated bioinformatics

This pipeline does **not** use BWA, GATK, or any accepted alignment/variant
caller, and makes **no claim of biological validation, accuracy, or
GATK/GIAB concordance**:

- **Alignment** places every synthetic read at position 1 with a
  full-length `<len>M` CIGAR, because every synthetic read is itself a
  full-length copy of the reference (with 0 or 1 known injected SNPs). This
  is a fixed, known placement, not seed-and-extend mapping. Real BAM/CRAM
  formatting, sorting, and indexing are produced by `samtools`, which is a
  real, standard tool -- only the "aligner" upstream of it is a stub.
- **Variant calling** tallies, at each reference position, the most common
  non-reference base across all reads and calls a variant when its fraction
  meets a threshold (default 0.3), assigning genotype `1/1` at >=0.9 or
  `0/1` otherwise. It is a naive per-position mismatch counter, not a
  probabilistic/haplotype-aware caller.
- Both stages are checked only against the pipeline's own synthetic,
  self-injected truth positions (`sample["truth_variants"]`), which is
  sufficient to prove the pipeline's data flow and provenance/failure
  behavior end-to-end, but proves nothing about accuracy on real sequencing
  data.

## samtools/bcftools and the WSL fallback

`scripts/secondary_pipeline.py::_resolve_tool()` looks for `samtools`
directly on `PATH` first (the portable, Linux/container case). Only on
Windows, and only if the tool is not already reachable, it additionally
checks whether the tool is available inside WSL and, if so, transparently
runs it there via `wsl -e bash -lc ...`, translating Windows paths to
`/mnt/<drive>/...` form. This is a development-sandbox convenience for
producing genuine BAM/CRAM output on a Windows machine; a container or Linux
CI runner satisfies the same code path directly via `PATH` with no WSL
involved. If `samtools` is unavailable through either route, `run_alignment`
degrades to writing plain SAM text so the pipeline still completes, with
`format_engine` recorded as `"stub-no-samtools"`.

## Synthetic data, never committed

`generate_demo_sample()` writes a tiny synthetic FASTA and paired FASTQ files
at runtime into a caller-supplied scratch directory; nothing genomic is ever
committed to the repository. `.gitignore` already excludes `*.vcf`, `*.bam`,
`*.cram`, `*.fastq`, `*.fasta`, `work/`, and `.nextflow*/` (see repository
root `.gitignore`). No real patient identifiers, protected health
information, or customer data appear anywhere in this pipeline; `sample_id`
values are synthetic strings such as `SYN-SAMPLE-0001`.

## Container definitions

`workflows/containers/quality-control.Dockerfile`,
`alignment.Dockerfile`, and `variant-calling.Dockerfile` define per-stage
container images (quality control: pure Python; alignment: Python +
samtools; variant calling: pure Python). These are configuration artifacts
only in this delivery -- they were not built or run in this sandbox because
no Docker daemon was available (Docker Desktop was installed but its daemon
was not running). `workflows/conf/docker.config` wires these images into
Nextflow's `docker` profile for an environment where a daemon is available.

## Azure Batch profile -- validated with a live run (task 5.2)

`workflows/conf/azure_batch.config` defines the Azure Batch executor
profile. Unlike the Slurm profile below, this profile has been exercised
end-to-end against a real, disposable Azure Batch account
(`rg-genomics-20260919`), not just written as configuration:

- **Credential-free by design.** The profile never embeds a storage key,
  SAS token, or registry password. Nextflow authenticates to both Azure
  Batch and the storage account (`allowSharedKeyAccess: false`) via
  `azure.managedIdentity.clientId`, and the pool's nodes pull the four
  per-stage container images from ACR via a pool-level
  `containerConfiguration.containerRegistries[].identityReference`
  (`infra/modules/batch.bicep`) -- a second, independent managed-identity
  path that never touches Nextflow's own (credential-based)
  `azure.registry` mechanism. A `.nextflow.log` grep for `sig=`,
  `sharedkey`, `accountkey`, and `SAS token` on the live run returned no
  matches; the log instead shows `ManagedIdentityCredential` bootstrapping
  for both the Batch client and the storage client.
- **Runs from Azure-hosted compute, not the dev machine.** `ManagedIdentityCredential`
  requires an IMDS endpoint, so `nextflow run -profile azure_batch` was
  executed from a temporary, already-authorized verification VM
  (`vm-genomics-20260919`) carrying the same user-assigned `batch` identity,
  via `az vm run-command invoke`, not from a local workstation.
- **Per-process containers.** `GENERATE_DEMO_SAMPLE`, `QUALITY_CONTROL`,
  `ALIGN_READS`, `CALL_VARIANTS`, and `PUBLISH_RESULTS` each declare a
  `container` directive in `azure_batch.config`, resolved from
  `AZURE_BATCH_ACR_LOGIN_SERVER`/`AZURE_BATCH_IMAGE_TAG` env vars (no
  hardcoded resource names). The three pre-existing Dockerfiles had their
  `ENTRYPOINT` removed (an ENTRYPOINT swallows Nextflow's generated
  `.command.run` wrapper instead of letting it execute); a new
  `workflows/containers/demo-sample.Dockerfile` was added for
  `GENERATE_DEMO_SAMPLE`, which previously had no image. All four images
  were built and pushed with `az acr build` (cloud build; no local Docker
  daemon required).
- **Pool sizing constraints discovered live, not assumed.** This Azure
  Batch account defaults most modern VM families
  (`standardDSv5Family`, `standardDasv5Family`, `standardDv5Family`, etc.)
  to a **0-core quota**, invisible from subscription-level `az vm
  list-usage`; only certain older families
  (`standardDSv3Family`, `standardDv3Family`, `standardEv3Family`, etc.)
  have a usable default (500 cores). Separately, the pool's
  `microsoft-dsvm`/`ubuntu-hpc`/`2404` image is Gen2-only, which rules out
  Gen1-only SKUs such as `Standard_D2_v3`. `poolVmSize` is therefore
  `Standard_D2s_v3` (DSv3 family: Gen2-compatible and has quota) --
  the only combination of the four tried that actually provisioned nodes.
- **Two-identity RBAC.** The batch managed identity itself (not only the
  human deployer) needs "Azure Batch Account Contributor" to submit/poll
  tasks against an AAD-only Batch account (`allowedAuthenticationModes:
  ['AAD', 'TaskAuthenticationToken']`, no shared key) -- added as a second
  role assignment in `infra/modules/batch.bicep`.

### Manual verification evidence -- Azure Batch (task 5.2)

Run `azure-batch-live-006` executed the full five-process pipeline on the
live `secondary-analysis-pool` and completed successfully:

```
QUALITY_CONTROL      | 1 of 1
ALIGN_READS          | 1 of 1
CALL_VARIANTS        | 1 of 1
PUBLISH_RESULTS      | 1 of 1
Succeeded   : 5
```

It produced a real BAM (`SYN-SAMPLE-0001.bam`), its index (`.bam.bai`), a
VCF (`SYN-SAMPLE-0001.vcf`), and `qc_report.json` (`passed: true`,
12 synthetic reads per mate). Its provenance record includes the complete
field set used by the local/standard profile at the time of that live run:

```json
{
  "run_id": "azure-batch-live-006",
  "workflow_id": "genomics-secondary-analysis",
  "workflow_version": "v0.1.0",
  "reference_build": "SYN-demo-genome",
  "reference_version": "synthetic-1385e2e921c4",
  "execution_target": "azure_batch",
  "compute_pool": "secondary-analysis-pool",
  "terminal_state": "succeeded",
  "failing_stage": null,
  "input_uris": ["az://batch-work/nextflow-work/.../SYN-SAMPLE-0001_R1.fastq", "..."],
  "output_uris": ["file:///home/azureuser/batch-run/results/SYN-SAMPLE-0001.bam", "..."],
  "start_time": "2026-09-21T03:32:59Z",
  "end_time": "2026-09-21T03:35:10Z",
  "log_location": "file:///home/azureuser/batch-run/.nextflow.log"
}
```

Nextflow's work directory (`az://batch-work/nextflow-work`) lives in a
private, `allowSharedKeyAccess: false` storage account; results were staged
back to the verification VM's local disk by `PUBLISH_RESULTS`. After the
run, the pool's autoscale policy (evaluated every `PT5M`) drained back to
`currentDedicatedNodes: 0` with `allocationState: steady`, confirmed via
`az batch pool show` -- compute releases to zero when idle rather than
running (or billing) continuously (see task 5.7 in
`openspec/changes/add-genomics-variant-accelerator/tasks.md`).

### Burst-concurrency compute release evidence (task 5.7)

Task 5.7 required stronger evidence than the single successful run above: the
pool had to scale for a **concurrent burst** and then return to zero only after
those runs reached terminal state. On September 21, 2026, two independent
Azure Batch profile runs (`azure-batch-burst-001`, `azure-batch-burst-002`)
were launched in parallel from the same verification VM, each with a distinct
`--run_id` and isolated `az://batch-work/nextflow-work/<run_id>` work path.
Both runs completed successfully at `2026-09-21T13:46:23Z`, and each published
the expected BAM, BAI, VCF, QC report, reference FASTA, manifest, and paired
FASTQ inputs back onto the VM under `/root/batch-burst/<run_id>/results`.

Live pool polling during that burst showed the autoscale policy allocate real
concurrent capacity, not just reuse the single-run evidence from task 5.2:

- `2026-09-21T13:43:27Z`: `currentDedicatedNodes: 2`,
  `targetDedicatedNodes: 2`, `allocationState: steady`,
  `autoScaleRun.results = $TargetDedicatedNodes=2; ...; $tasks=2`
- `2026-09-21T13:47:35Z`: `currentDedicatedNodes: 2`,
  `targetDedicatedNodes: 1`, `allocationState: resizing`,
  `autoScaleRun.results = $TargetDedicatedNodes=1; ...; $tasks=1.6`
- `2026-09-21T13:48:08Z`: `currentDedicatedNodes: 1`,
  `targetDedicatedNodes: 1`, `allocationState: steady`
- `2026-09-21T13:52:34Z`: `currentDedicatedNodes: 1`,
  `targetDedicatedNodes: 0`, `allocationState: resizing`,
  `autoScaleRun.results = $TargetDedicatedNodes=0; ...; $tasks=0`
- `2026-09-21T13:53:08Z`: `currentDedicatedNodes: 0`,
  `targetDedicatedNodes: 0`, `allocationState: steady`

That sequence demonstrates the contract in the secondary-analysis spec's
"Elastic compute allocation" requirement: concurrent submissions caused the
pool to allocate two dedicated nodes, and the same pool released them back to
zero after the burst had fully drained. The verification VM used to submit the
burst was deallocated again afterwards to avoid idle VM cost.

`scripts/run_nextflow_secondary_pipeline.py` still hardcodes
`-profile standard` and does not yet parametrize `-profile azure_batch`;
this run's provenance was recorded directly against
`scripts/pipeline_provenance.record_run` rather than through that launcher.
Extending the launcher to drive the Azure Batch profile automatically is a
follow-on hardening item, not a blocker for this task.

## Slurm and ephemeral Managed Lustre campaign

`scripts/hpc_campaign.py` is the single campaign entry point. Its `validate`
action performs local-only input and compatibility validation and can generate
a tiny synthetic bundle in a caller-selected temporary directory. Its `run`
action is intentionally live and must be invoked only with explicit Azure
authorization and budget approval.

The path implements these fail-closed boundaries:

- It requires the campaign id and owner, subscription, region, SSH public key,
  an explicit private Slurm image id, and the exact reference build, immutable
  version, and manifest SHA-256. Compatibility is checked before any Azure
  command that creates a resource.
- `infra/hpc-campaign.bicep` creates only ephemeral campaign resources:
  private VNet/subnets and DNS, private Blob/DFS endpoints to an explicitly
  selected accelerator storage account, a scheduler VM, and AMLFS scratch.
  AMLFS has no HSM settings. The separately owned private HNS storage account
  and staging identity survive campaign teardown so copied results, logs, and
  provenance remain available.
- The selected image must already contain a configured single-node Slurm
  scheduler/worker with an available partition, the matching AMLFS Lustre
  client and `mount.lustre`, AzCopy, Java and Nextflow, Python 3, samtools,
  `sudo`, `mountpoint`, `findmnt`, `sha256sum`, GNU `find`/`sort`/`xargs`, and
  this repository at the declared POSIX path. The VM identity must be able to
  read and write the declared Blob locations; the Azure control-plane caller
  must be allowed to invoke VM Run Command, and the image's admin user must
  have passwordless `sudo` for the AMLFS mount. Docker is not required: the
  Slurm profile sets `docker.enabled = false` and runs the image-pinned host
  tools directly.
  The Slurm profile runs those image-pinned host tools directly rather than
  reaching ACR during the private campaign. This avoids public package or
  container downloads after the campaign starts.
- The VM mounts AMLFS, generates the minimal synthetic input at runtime,
  uploads it to the private input container through AzCopy managed-identity
  login, deletes the local seed, copies it back into the mounted POSIX path,
  and verifies its SHA-256 manifest before invoking the existing Nextflow
  Slurm profile.
- Result files receive an `OUTPUT-SHA256SUMS` manifest, are copied to the
  private output container with the same managed identity, downloaded to an
  independent verification directory, and checked before success is emitted.
  Nextflow logs, launcher output, terminal state, and the SQLite provenance
  record are copied to the private log container.
- The launcher records durable Blob input, output, and log URIs in Slurm run
  provenance rather than ephemeral `/mnt/amlfs` paths. Local executions retain
  their existing `file://` provenance.
- Success, worker failure, and unverified copy-out all enter synchronous
  teardown from the orchestrator's `finally` path, but deletion proceeds only
  after the resource group's project, component, campaign-id, and owner tags
  all match the invocation. The worker attempts to copy failure logs to the
  durable log prefix before returning failure; campaign scratch is not retained
  for diagnosis.
- `workflows/conf/slurm.config` refuses to start without an explicit
  `SLURM_LUSTRE_WORKDIR`, preventing accidental use of node-local scratch.

Example local/static validation (the values are non-live examples):

```powershell
python -m scripts.hpc_campaign `
  --action validate `
  --subscription-id "<subscription-id>" `
  --location eastus2 `
  --campaign-id synthetic-001 `
  --campaign-owner SYN-OWNER-001 `
  --admin-public-key "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAISyntheticOnly" `
  --slurm-image-id "/subscriptions/<subscription-id>/resourceGroups/rg-images/providers/Microsoft.Compute/galleries/genomics/images/slurm-synthetic/versions/2026.9.28" `
  --staging-identity-resource-id "/subscriptions/<subscription-id>/resourceGroups/rg-genomics-syn/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-genomics-staging" `
  --staging-identity-client-id 11111111-1111-1111-1111-111111111111 `
  --staging-identity-principal-id 22222222-2222-2222-2222-222222222222 `
  --staging-storage-account-id "/subscriptions/<subscription-id>/resourceGroups/rg-genomics-syn/providers/Microsoft.Storage/storageAccounts/stglakesynthetic" `
  --staging-storage-account-name stglakesynthetic `
  --staging-environment synthetic `
  --reference-build SYN-demo-genome `
  --reference-version synthetic-1385e2e921c4 `
  --reference-manifest-sha256 7e3be36672095e4018dfded5466ddb002848387e19d314595cb1a128a231be83
```

The earlier September 24, 2026 campaign remains only evidence that a private
VM could run Slurm and mount AMLFS. It did not exercise this revised
managed-identity copy path. Task 5.3 therefore remains pending until a bounded
live campaign proves creation, stage-in, workflow use, verified copy-out, and
guarded teardown together.

The revised September 27, 2026 attempt did not create campaign resources. It
proved the exact reference build/version/digest gate locally, confirmed live
AMLFS quota and VM SKU availability, and compiled the Microsoft AMLFS 2.17
DKMS client on a private Trusted Launch builder. Azure then held that builder
in `ProvisioningState/updating` after Secure Boot was disabled for the DKMS
module. Because a trustworthy private image could not be captured, the
orchestrator's image preflight was not bypassed. The tagged builder group was
deleted, and read-only checks found no campaign or image-builder resources.
See the redacted
[`slurm-lustre-revised-live-2026-09-27.json`](../openspec/changes/add-genomics-variant-accelerator/evidence/slurm-lustre-revised-live-2026-09-27.json)
record.

The September 28 recovery supersedes that image-build design without rewriting
the historical result. The current builder installs the matching prebuilt
Microsoft-signed kmod, keeps Secure Boot and vTPM enabled on the separate
Trusted Launch validation VM, and rejects Docker or a repository commit that
lacks the explicit Lustre work directory, durable URI arguments, reference
manifest gate, and host-tool Slurm profile. It also refuses an existing image
version and reports cleanup failures. The live action was intentionally
stopped by that immutable-source gate because the required repository changes
are still in the uncommitted working tree. Read-only post-checks found no
recovery build, staging, validation, or gallery resource group. See the
redacted
[`private-slurm-image-recovery-2026-09-28.json`](../openspec/changes/add-genomics-variant-accelerator/evidence/private-slurm-image-recovery-2026-09-28.json)
record.

## Manual verification evidence

Both the pure-Python orchestrator and the real Nextflow workflow were run
directly (not merely unit-tested) for both outcomes:

- **Success:** `scripts/run_secondary_pipeline.py` and
  `scripts/run_nextflow_secondary_pipeline.py` both produced a BAM, its
  index, a VCF, and a QC report, with a provenance record showing
  `terminal_state = "succeeded"`, `failing_stage = null`, and four published
  output URIs.
- **Forced failure:** invoking either entry point with
  `--force-fail-stage variant_calling` (or the Nextflow equivalent
  `--force_fail_stage variant_calling`) produced `terminal_state = "failed"`,
  `failing_stage = "variant_calling"`, and an empty `output_uris` list, with
  no publish directory created and no partial BAM/VCF treated as a
  completed result. The Nextflow run's failure was independently confirmed
  by Nextflow's own `ERROR ~ Error executing process > 'CALL_VARIANTS'`
  output, parsed by the external wrapper to identify the stage.
- Nextflow 26.04.6, samtools/bcftools 1.23.1 were installed and run inside
  WSL (Fedora) for this verification; they are not committed to the
  repository and are not required to run the pure-Python test suite.

## Known discrepancy in the spec text

`specs/processing/secondary-analysis/spec.md`'s run-provenance requirement
says to "verify all ten fields are present," but its own enumerated list
names twelve distinct values (workflow id, workflow version, reference
build, reference version, execution target, compute pool, input URIs,
output URIs, start time, end time, terminal state, log location). This
implementation records and validates all twelve rather than dropping two to
match the word "ten," on the basis that under-implementing a named field to
satisfy a miscounted total would be worse than over-delivering against it.
This discrepancy should be corrected in the spec text itself in a future
OpenSpec revision; it is not silently resolved here.