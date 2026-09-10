# Local Infrastructure Preparation

Status: candidate inventory and local validator implemented. **No Bicep templates
have been generated and nothing is deployable.** The inventory is not an approved
infrastructure plan or evidence of Azure resource compatibility.

Azure operations are paused at the user's request. Do not authenticate to Azure,
enumerate subscriptions, provision resources, upload artifacts, seed cloud data,
run benchmarks, or execute teardown as part of this phase. Local validation does
not authorize any of those operations. No cloud deployment workflow is installed.

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
success is not evidence of a remote CI run for these uncommitted changes.

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

OpenSpec progress is **3/89 completed tasks**, including the separately implemented
[local scheduled inventory](../docs/landing-inventory.md) in task 2.1. This preparation does not
complete tasks 1.3 or 1.4, or any cloud acceptance task. The 100 GiB SMB benchmark,
observed IOPS ceiling, directory/ACL tests, denied-access cases, repeat deployment,
reset, teardown and cost measurements remain pending. No live guarantee of
performance, security, availability, compliance or idempotency is claimed.