# Local Infrastructure Preparation

## HPC campaign implementation

`infra/hpc-campaign.bicep` and `scripts/hpc_campaign.py` implement the revised
single-campaign Slurm path. AMLFS is ephemeral POSIX scratch only; native HSM
import/export is not configured. An explicitly selected accelerator staging
identity uses AzCopy against an existing private HNS storage account, with
shared-key access and public storage access disabled. The durable account,
identity, and image must carry the expected accelerator ownership tags; only
the ephemeral campaign resource group is deleted.

The local-only validation action checks identifiers, ownership inputs, the
explicit reference build/version/manifest digest, and workflow compatibility.
It can generate a minimal synthetic bundle under a caller-supplied temporary
directory. It does not contact Azure:

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

The `run` action is a live, billable operation and was not executed for this
implementation. It requires a prebuilt private image containing Slurm, the
Lustre client, AzCopy, Java and Nextflow, Python 3, samtools, standard Linux
mount/checksum utilities (`mount.lustre`, `mountpoint`, `findmnt`, `sha256sum`,
GNU `find`/`sort`/`xargs`, and passwordless `sudo`), and this repository at the
declared path. It must also provide a configured single-node Slurm
scheduler/worker and the requested partition. Docker is not required because
the Slurm profile runs image-pinned host tools directly.
The template has no marketplace-image fallback. On success or failure, the
orchestrator enters guarded synchronous teardown from a `finally` path and
deletes only a resource group whose ownership tags exactly match the
invocation. Failure diagnostics must therefore be copied to durable Blob
storage by the worker before teardown; if that copy also fails, only the
orchestrator error remains.

Status: parameterized Bicep exists for the accelerator foundation and the
separate HPC campaign. The campaign path has local/static validation only in
this change; it has not been deployed or accepted live.

## Private Slurm image

`infra/slurm-image-gallery.bicep`, `infra/slurm-image-builder.bicep`,
`infra/scripts/configure-slurm-image.sh`, and
`scripts/build_slurm_image.py` define the private image prerequisite for the
campaign. The implementation builds a no-public-IP Ubuntu 24.04 Gen2 Trusted
Launch VM in a disposable private build resource group, configures it through
VM Run Command, verifies the pinned kernel and Secure Boot before capture,
deprovisions and generalizes the VM, and captures it directly into Azure
Compute Gallery. The image definition remains Ubuntu 24.04 Gen2 with
`SecurityType=TrustedLaunchSupported`, which is the gallery feature that
permits Trusted Launch VM deployments from the generalized image.

The build pins the Canonical source version and running Azure kernel, installs
the matching Microsoft prebuilt AMLFS kmod package rather than DKMS, verifies
the Microsoft package-signing key fingerprint, and checksum-verifies the
Nextflow and AzCopy release assets. It installs the required Slurm, AMLFS,
AzCopy, Java, Nextflow, Python, samtools, mount/checksum, service, partition,
and repository interfaces without Docker. The selected repository commit must
be fetchable and must already contain the audited no-Docker Slurm profile,
explicit Lustre work directory, durable URI options, and reference-manifest
gate.

The orchestrator refuses an existing gallery image version and creates no build
storage account, shared key, SAS, public IP, NAT gateway, Azure VM Image Builder
template, AIB identity, or AIB staging resource group. It validates the retained
version on a separate no-public-IP Trusted Launch VM with Secure Boot and vTPM
enabled. Validation checks the Microsoft-signed Lustre module, `mount.lustre`,
required tools and services, Slurm partition, repository commit/interface, and
unchanged VM security profile. Build and validation resources are synchronously
removed after success or failure. An image version is retained only after full
validation; an owned unvalidated version is deleted, and cleanup failures are
reported rather than suppressed.

Recovery validation on September 28, 2026 compiled both image Bicep templates,
passed the focused Python tests and static configuration validation, and
confirmed the pinned source is Gen2 and `TrustedLaunchSupported`. On September
29, 2026 the Image Builder path was replaced before live acceptance because AIB
creates an internal staging storage account and writes VHDs with shared-key
access, which the subscription policy rejects. The replacement Trusted Launch
VM capture path is locally tested and Bicep-compiled, but no live capture has
yet been validated and no validated gallery image exists yet.

Azure operations require explicit task-level authorization. The September 28
image recovery included read-only source/quota checks and one bounded live
entry-point invocation; the immutable-source gate stopped it before resource
creation. Local validation by itself does not authorize provisioning, uploads,
benchmarks, campaigns, or teardown.

## Run Locally

Required tools: PowerShell 7.2+ (`pwsh`) for validation; Python 3.10+ and Git for
the repository tests. No Azure CLI, Azure credentials, or third-party Python
packages are required. Run from the repository root:

```powershell
./scripts/Invoke-Infrastructure.ps1 -Action Validate | ConvertTo-Json -Depth 4
python -m unittest discover -s tests -p 'test_infrastructure.py' -v
```

From a non-PowerShell shell:

```sh
pwsh -NoLogo -NoProfile -NonInteractive -File scripts/Invoke-Infrastructure.ps1 -Action Validate
```

Validation uses [asset-inventory.schema.json](asset-inventory.schema.json) to
check [asset-inventory.json](asset-inventory.json). It rejects duplicate asset
IDs, unknown dependencies, dependency cycles and task IDs missing from the
[OpenSpec task list](../openspec/changes/add-genomics-variant-accelerator/tasks.md).
It reports a dependency-respecting preparation order. Paths are resolved from
the script location, so validation also works when invoked from another directory.

The only supported action is `Validate`. `Deploy`, `Apply`, `Preflight`, `WhatIf`,
`Login` and `Teardown` are rejected during argument binding, before any input file
is read. There is no override flag and no external-process or network invocation
in the validator. This constrains this entry point, not arbitrary commands a
contributor could run elsewhere.

A successful result means the **inventory** is valid. It always reports:

```text
TemplatesBuilt: false
AzureReadiness: not-evaluated
DeploymentSupported: false
```

It does not compile Bicep, validate ARM schemas, check regional availability,
calculate costs, prove RBAC or connectivity, or establish deployment readiness.
The existing repository test workflow discovers the new synthetic tests; local
success is not evidence of a remote CI run for the current changes.

## Local Write Smoke Test

[Test-LandingWrite.ps1](../scripts/Test-LandingWrite.ps1) exercises the write,
flush, read-back and cleanup mechanics needed for the future task 1.3 benchmark.
It requires PowerShell 7.2+ and an existing absolute directory on a fixed local
drive. It does not connect to Azure or an SMB share. For a small synthetic check:

```powershell
./scripts/Test-LandingWrite.ps1 -Directory ([IO.Path]::GetTempPath()) -ByteCount 1048593
python -m unittest discover -s tests -p 'test_infrastructure.py' -k LandingWrite -v
```

The default write is 16 MiB; accepted sizes range from one byte to 1 GiB. The
command checks available space with a 16 MiB reserve and creates one uniquely
named scratch file without overwriting existing files. The file uses
`DeleteOnClose` and its stream is disposed in `finally`. Normal cleanup and
preservation of sibling files are covered by tests; process-kill and power-loss
recovery have not been tested.

UNC/device paths, network/removable drives, relative paths, dot path segments,
and symlink/junction/reparse-point ancestors are rejected. There is no network
override. Use a trusted local scratch directory: these checks are not a security
sandbox against concurrent path changes or every OS-specific mount mechanism.

The JSON report includes exact byte count, elapsed seconds, MiB/s, expected and
read-back SHA-256 digests, integrity status and cleanup status. Timing covers
sequential writes and `Flush(true)`, excluding file creation, synthetic-buffer
generation, hashing and cleanup. The random buffer is at most 1 MiB and is reused;
caching, compression and storage-stack behavior can affect the rate. Read-back
integrity does not prove persistence after a power failure.

Every report is labelled `local-smoke`, with `SmbAcceptancePassed: false`,
`IopsCeilingVerified: false` and `AzureReadiness: not-evaluated`. Neither the
100 GiB SMB measurement nor the provisioned IOPS ceiling is tested here. Network
benchmark execution remains disabled pending separately authorized cloud work;
do not use local rates as Azure performance evidence.

## Candidate Asset Coverage

The machine-readable inventory groups the planned work into:

| Group | Candidate assets |
| --- | --- |
| Network | VNet, subnets, NSGs, private endpoints and private DNS |
| Identities | Separate runtime and deployment identities, scoped grants, OIDC |
| SMB landing | Classic SSD provisioned-v2 share, sizing and SMB Multichannel |
| Object storage | HNS lake, blob/dfs endpoints, taxonomy initializer, references |
| Secrets and audit | Key Vault, diagnostics and independently controlled retention |
| Staging | Scheduled discovery, Data Factory Copy and private runtime connectivity |
| Catalog and lifecycle | Purview integration and blob-side Storage Actions |
| Registry | Private ACR and publication/attestation definitions |
| Batch | Private compute and zero-idle-node executor configuration |
| HPC | Slurm campaign infrastructure and ephemeral Managed Lustre |
| Analytics | Engine-specific workspaces, governed stores and query access |
| Delivery | Validation, later preflight, deployment, cost, reset and teardown assets |

Each group records task references, dependencies and unresolved decisions. These
are work packages, not an ARM resource list: provider types, API versions, naming
rules, service pairings and regional support still require validation. Bicep is
the proposed implementation language, not yet an approved design decision.

## Decisions Before IaC

The infrastructure planning workflow requires explicit approval of a researched
resource list and concrete plan before IaC generation. The user was unavailable
for that approval, so the inventory remains `candidate-awaiting-review`. An
unavailable response is not approval. No fabricated environment insights or
approved plan have been written.

Start by reviewing the common storage/network/identity foundation. Research can
use public documentation and schemas without querying an Azure account. Keep
Fabric versus Databricks open until explicitly selected; Batch and HPC remain
alternative executors, with neither enabled automatically.

Important decisions still needed:

- Lab routing, DNS, directory authentication and preservation of the existing
  instrument UNC path. A new share alone does not satisfy unchanged write paths.
- Lowercase container names versus case-preserving `Ingest`, `Process`, `Failed`,
  `External`, `Inventory`, `ReferenceData` and `SampleData` directories. Directory
  creation and ACLs need a later data-plane initializer, not merely ARM containers.
- Private Data Factory runtime placement, SMB authentication and least-privilege
  transfer access. Managed-identity support must be checked per connector/protocol.
- A supported HNS reference-immutability mechanism and scoped publisher grants.
- Region, redundancy, sizing, retention and dated cost estimates. No values have
  been inferred from the author's Azure environment.

After plan approval, local IaC work should add parameterized modules under
`infra/modules/`, an entry template, marked example parameters and compiler plus
compiled-template security tests. Registry module restoration may download public
dependencies; it must not publish anything. Keep future cloud preflight and
deployment separate from local compilation, fail closed without explicit
authorization, and add no automatic deployment trigger.

## Deferred Acceptance

OpenSpec progress is **8/89 completed tasks**, including the separately implemented
[local scheduled inventory and completeness checks](../docs/landing-inventory.md)
in tasks 2.1 and 2.2 and [local metadata lineage/integrity](../docs/metadata-store.md)
in tasks 6.1 through 6.4 (lineage, file details, integrity and metadata-only archival). The [reference submission gate](../docs/reference-submission.md)
integrates the local workflow submission path with the published-reference abstraction for task 4.3; it does not claim a deployed cloud workflow.
This preparation does not
complete tasks 1.3 or 1.4, or any cloud acceptance task. The 100 GiB SMB benchmark,
observed IOPS ceiling, directory/ACL tests, denied-access cases, repeat deployment,
reset, teardown and cost measurements remain pending. No live guarantee of
performance, security, availability, compliance or idempotency is claimed.

## Remaining Implementation Gates

The request to implement the remaining work without excessive subscription spend
does not establish a currency, limit, region or approved resource plan. Azure
access remains paused; no account discovery is needed to run the local tests.

| Work | Required input before continuation |
| --- | --- |
| Failed transfer and staging (2.3, 3.x) | Trusted expected size/checksum or vendor transfer-status contract; stability alone also accepts paused/truncated writes |
| Reference/pipeline integration (4.x, 5.x) | Published checksum inventory, reviewed workflow/build/annotation compatibility, actual Nextflow pipeline and a defined concordance threshold |
| Infrastructure and live acceptance | Reviewed resource list and concrete plan, region, sizing, numeric per-delivery/idle spending limits, and separate deployment authorization |
| Variant store and governed analytics (6.x-9.x) | Fabric versus Databricks, annotation strategy and access/identity model; do not claim a local substitute proves service grants |
| Releases and delivery (10.x-12.x) | Real pipeline artifacts and deployed acceptance evidence; do not publish fabricated releases, cost measurements or end-to-end KPIs |

The validator has no deploy action. Neither executor is enabled automatically.
Local tests generate tiny temporary synthetic fixtures, not downloaded genomes.
Do not turn on both compute paths or a provisioned analytics service merely to
advance task checkboxes. This is a local execution boundary, not a hard cap on
other activity in a subscription. Existing Azure resources, if any, were not
queried and their charges are unknown.