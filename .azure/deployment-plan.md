# Azure Deployment Plan

Status: Partial fresh foundation retained; verification VM deallocated
Date: 2026-09-19
Change: add-genomics-variant-accelerator
Mode: Disposable acceptance environment

## Authorization And Scope

The user authorized Azure operations in their MCAPS subscription for real
end-to-end implementation tests, followed by removal of all resources created
for those tests. This supersedes the earlier local-only pause. Existing resources
and unrelated workloads must not be modified or deleted.

The current work is authorized under a USD 150 total ceiling in `eastus2`.
The tagged boundary is `rg-genomics-20260919`, with an October 3, 2026 expiry.
Credentials, subscription identifiers and tenant identifiers must not be
committed to Git or the wiki.

## Implementation Sequence

1. Confirm Azure context, cost envelope and an isolated resource-group boundary.
2. Implement parameterized Bicep, preflight, deployment inventory and scoped
   teardown before provisioning the storage foundation.
3. Validate SMB landing, failure detection, integrity-checked ADLS staging and
   least-privilege access using only synthetic or approved public demo data.
4. Implement reference publication and the real Nextflow processing path; test
   executor profiles and persist execution provenance without storage keys.
5. Implement Delta ingestion, governed query surfaces and end-to-end lineage.
6. Run the specified demo, negative tests and measured acceptance checks; retain
   non-sensitive evidence, update OpenSpec and wiki, and remove test resources.

The complete OpenSpec scope remains in force. Expensive components, including
Managed Lustre, and alternate executor tests require explicit sizing and cost
review; a smaller test cannot silently satisfy their acceptance criteria.

## Resource Inventory And Capacity

Region `eastus2`, one resource group named `rg-genomics-<environment>`, tagged
`project=genomics-variant-accelerator` and `lifecycle=disposable-test` with an `expiresOn`
date. `Remove-Accelerator.ps1` refuses to delete a group without that tag.

| Component | Purpose |
|---|---|
| Three user-assigned identities | Separate ingestion, staging and processing grants |
| SSD provisioned v2 file share | SMB landing zone, Multichannel enabled |
| ADLS Gen2 account with HNS | Staged artifacts under the healthcare folder taxonomy |
| VNet, NSG, three private endpoints, private DNS zones | Private-only data planes |
| Linux verification client | Runs data-plane acceptance checks through run-command |

Concrete subscription, tenant and resource identifiers are written to
`.azure/environment.env.json`, which is untracked. This repository is public, so no
subscription id, tenant id or environment-specific name belongs in a committed file.

## Governance Constraints Discovered

These are subscription policy, not configuration defects, and must not be worked around:

- `publicNetworkAccess` is forced to `Disabled` on storage accounts. The template requests
  `Enabled` and policy reverts it, so all data-plane access is via private endpoint.
- `allowSharedKeyAccess` is forced to `False`. Azure Files SMB NTLMv2 authenticates with that key,
  so key-based mounting is unavailable by design. The landing account therefore enables
  `azureFilesIdentityBasedAuthentication.smbOAuthSettings.isSmbOAuthEnabled` and clients mount with
  `sec=krb5` as a managed identity. The property is nested under
  `azureFilesIdentityBasedAuthentication` and requires API version 2025-08-01; setting it at the top
  level of `properties` is silently ignored.
- Public IP addresses cannot be created, so NAT Gateway, Azure Firewall and VM public
  addresses are unavailable. The client is driven through run-command instead.
- Only v7-family VM sizes are unrestricted in `eastus2`.
- Blob versioning is unavailable on hierarchical-namespace accounts, so reference
  immutability in task 4.2 cannot rely on it.

## Historical Verified Results

Produced by `scripts/Test-Environment.ps1` against the earlier disposable
environment that was removed on September 18, 2026:

| Check | Result |
|---|---|
| Taxonomy paths exist | 12 directories return 200 |
| Staging identity writes | File created |
| Processing identity write denied | HTTP 403 |
| Processing identity reads | HTTP 200 |
| Processing identity denied landing-share listing | HTTP 403 |
| SMB mount as managed identity | `sec=krb5`, no storage key |
| 100 GiB sequential write over SMB | 240 MiB/s in 426 s |
| Share provisioned ceiling | 3000 IOPS, 200 MiB/s |

The SMB write exceeds the provisioned rate while `allowSharedKeyAccess` stays disabled, which is the
acceptance task 1.3 requires.

## Current Fresh Deployment

Read back on September 19, 2026:

| Area | State |
|---|---|
| Identities, landing account, private endpoints, Data Factory | Resources exist; no fresh component acceptance claimed |
| Object-storage deployment | Failed |
| Storage Actions lifecycle deployment | Failed |
| Network redeployment | Cancelled during finalization |
| Verification VM | Deallocated |
| Resource-group expiry | October 3, 2026 |

Storage and networking resources remain deployed and may continue to accrue
cost. The retained group is not a ready environment and does not replace the
historical acceptance evidence above.

## Cost And Cleanup

- Create resources only inside an explicitly selected, new disposable boundary.
- Record every created resource and any subscription-scoped assignment.
- Do not repurpose or delete pre-existing resource groups, role assignments,
  identities, datasets, networks or analytics capacities.
- Price the selected sizes before creation; budgets are alerts, not hard caps.
- Define bounded test duration and teardown even after failed validation.
- Confirm the exact deletion target before cleanup; report retained, soft-deleted
  or externally hosted artifacts and verify no demo-created live resources remain.

## Execution Checklist

- [x] Confirm MCAPS subscription and region.
- [x] Confirm resource inventory, quotas and permission checks.
- [x] Generate infrastructure and the deployment entry point.
- [x] Deploy the storage, network and identity foundation.
- [x] Run landing-zone and object-storage acceptance checks.
- [ ] Implement staging, reference publication and the processing path.
- [ ] Implement the Delta store, governed analytics and demo enablement.
- [ ] Remove test resources and verify cleanup.

## Validation Proof

The earlier deployment was re-run to completion and supplied the historical
acceptance results above. The September 19 fresh deployment did not complete
all component deployments or idempotency acceptance. Local unit tests remain
separate evidence and do not verify cloud behavior.

Tear down the current group with
`./scripts/Remove-Accelerator.ps1 -EnvironmentName 20260919`. The provisioned
share, storage and networking resources can bill while retained. The
verification VM is currently deallocated.