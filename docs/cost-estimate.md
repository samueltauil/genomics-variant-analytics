# Foundation cost estimate

**Status:** current retail-price estimate, not an invoice or a spending cap.
**Date retrieved:** September 19, 2026. **Region:** `eastus2`. **Currency:** USD.
**Ceiling for this run:** USD 500 total, authorized for the `20260919` disposable
environment (raised from an initial USD 150 ceiling on 2026-09-21 to allow
previously blocked dependent work -- Purview, Slurm/Managed Lustre, and a
governed-query analytics engine -- to be attempted). This document is the
pre-provisioning forecast required before that authorization is exercised;
deployment is refused if the forecast exceeds it.

This model is intentionally limited to the resources that the current
`infra/main.bicep` deploys by default, including the account-native storage
lifecycle policy added for task 3.5. The legacy Storage Actions resources are
optional and disabled by default. This document does not make a claim about a full
end-to-end accelerator: Batch/HPC, Managed Lustre, a Delta engine, analytics
capacity, genomic payload retention, data transfer, transactions, staging
pipeline execution, taxes, discounts, and support plans are not sized in this
repository and are excluded. Microsoft Purview (task 3.4) is also excluded: see
"Purview: priced but not deployed" below.

The prices below are Microsoft retail USD rates from the unauthenticated
[Azure Retail Prices API](https://prices.azure.com/api/retail/prices), whose
purpose and USD retail-rate semantics are documented by
[Microsoft Learn](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices).
The [Azure Files pricing page](https://azure.microsoft.com/pricing/details/storage/files/)
confirms that provisioned-v2 shares bill hourly for provisioned storage, IOPS,
and throughput regardless of use. Refresh this document before any deployment;
do not treat it as a quote.

## Sizing and calculation

| Resource | Bicep sizing | Retail meter and rate | Calculation |
|---|---:|---:|---:|
| SSD provisioned-v2 SMB share | 128 GiB, 3,000 IOPS, 200 MiB/s | SSD LRS provisioned storage: $0.000137/GiB-hour; provisioned IOPS: $0.000037/IOPS-hour; provisioned throughput: $0.000054/MiB/s-hour | `128 × .000137 + 0 × .000037 + 100 × .000054 = $0.022936/hour` |
| Verification VM while running | `Standard_D4s_v7`, Linux | $0.265/hour | `runtime hours × $0.265` |
| Verification VM OS disk | 32 GiB Standard LRS | S4 LRS disk: $1.536/month | `$1.536 / 730 hours = $0.002104/hour` |
| ADLS Gen2, identities, VNet, NSG, DNS zones, resource group, and Data Factory definition | Standard LRS hot account; no payload or triggered activity in the model | No fixed idle amount modelled | Usage-based storage, operations, pipeline activity, and data transfer are deliberately excluded. |
| Private endpoints | Three endpoints | Not included in the totals because the current Azure Retail Prices API response did not return an `eastus2` Private Link meter. | The Azure Private Link pricing page and Microsoft Learn confirm endpoint-hour and data-processing charges; refresh with the Pricing Calculator/API before approval. |
| Account-native lifecycle policy (task 3.5) | One path-prefix and age rule on the HNS lake | No separate task-execution resource is deployed; normal storage operation charges remain usage-based. | Operations on the synthetic acceptance object are excluded with the other unsized storage transactions. |

The share's first 3,000 IOPS and first 100 MiB/s are zero-priced in the
retrieved meter set. The table therefore charges only the 100 MiB/s above the
included throughput, and no IOPS increment.

## Purview: priced but not deployed (task 3.4)

Retail Purview meters (`eastus2`, retrieved 2026-09-19) show the Data Map
starts at one capacity unit and bills continuously while the account exists,
not only while it is scanned or queried: **Standard Capacity Unit $0.411/hour
≈ $9.86/day**, plus per-hour scanning-vCore meters if a scan actually runs.
That is a standing charge for as long as the account is alive, unlike every
other resource in this model, which is either usage-based or already
deallocated between uses. This foundation is authorized to stay up for
dependent HPC/end-to-end work of unknown duration, so an always-on $9.86/day
liability is material against the $500 ceiling if left running by mistake.
Deploying Purview would also require private endpoints and DNS zones for the
account/portal/ingestion endpoints to satisfy the "public data-plane disabled"
requirement (task 8.7); `infra/` does not yet model those. A live preflight on
September 21, 2026 confirmed the immediate environment blocker: the
`Microsoft.Purview` provider is `NotRegistered`, no Purview account exists in
the disposable resource group, and the Azure CLI Purview extension is not
installed. Task 3.4 therefore remains unchecked. This is an environment and
infrastructure-readiness blocker, not evidence that Purview lineage is
infeasible in principle. A future authorized attempt should first add and
review the private account/endpoints/DNS deployment, then provision Purview in
its own short-lived deployment, capture lineage evidence, and delete the
account immediately rather than adding it to the persistent foundation.

## Decision figures

| Figure | Amount | Scope and dominant resources |
|---|---:|---|
| **One delivery, minimum modeled foundation** | **$0.141** | Three-hour environment: 3 hours of the configured share ($0.068808), 15 minutes of the verification VM ($0.066250), and 3 hours of its 32 GiB OS disk ($0.006312). This assumes the deployment script deallocates the VM after its in-network setup. It excludes private endpoints, payload/operations, and every unsized workload service. |
| **Idle per day, minimum modeled foundation** | **$0.601/day** | Configured provisioned-v2 SSD share: `24 × $0.022936 = $0.550464`; 32 GiB OS disk: `24 × $0.002104 = $0.050496`. The share dominates this bounded total. |
| **VM left running, additional daily exposure** | **$6.360/day** | `24 × $0.265` for the verification VM, before its disk and other usage charges. This is why `Deploy-Accelerator.ps1` deallocates a VM that it started. |
| **Forecast for the `20260919` run against the $500 ceiling** | **≈ $0.14 delivery + $0.601/day idle** | At $0.601/day, the modeled foundation could stay up roughly 831 days before reaching $500 on idle storage cost alone; the ceiling is not at risk from this foundation while Purview stays undeployed. This excludes any HPC/Batch/Lustre/Purview/analytics-engine work a dependent todo later adds, which must be forecast and approved separately before it runs, and must stay within the remaining headroom below $500 total. |

**Approval rule:** use the live Pricing Calculator/API and the planned runtime,
payload, data-transfer, private-endpoint, disk, and service-capacity choices to
produce an approved estimate before provisioning. The figures above are useful
only for the currently parameterized foundation and must not be represented as
the cost of processing a sample or delivering the full architecture.
