# Solution engineer execution guide

Run a useful demo without pretending the whole architecture is deployed. This repository is a demo solution accelerator and reference architecture, not a released Microsoft blueprint or a turnkey service.

## Pick the right route

| Route | What you can show | Azure needed? |
|---|---|---|
| Local walkthrough (recommended) | Synthetic landing metadata, a local secondary-analysis run, provenance, and three failure controls | No |
| Foundation deployment | Selected storage and staging components in an approved subscription | Yes, billable |
| Slurm and AMLFS campaign | A private HPC execution path | Yes, billable, and live acceptance is still pending |

This guide runs the local route. It takes no Azure action and uses synthetic data only. Allow about 20 minutes for a first run and discussion; the commands themselves usually take less.

## Before the meeting

From a fresh clone, use Python 3.10 or newer, Git, and PowerShell 7.2 or newer. No Azure CLI, Azure login, Python packages, or genomic files are needed for the local walkthrough.

Read [coverage](coverage.md) to see what is demonstrated, partial, or still an architectural intention. Check the [claim register](claim-register.md) before a customer conversation. Keep the demo state under a dedicated temporary folder:

```powershell
$demo = Join-Path $env:TEMP 'genomics-se-demo'
New-Item -ItemType Directory -Force -Path $demo | Out-Null
```

## Run the walkthrough

### 1. Set expectations

Run the local preflight:

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File scripts\Test-DemoPreflight.ps1 |
  ConvertFrom-Json
```

In this mode, `Ready: false`, `BlockingFailures: 0`, and nine `UNVERIFIED` cloud checks are expected. The command checks local tools and repository files only. It does not inspect an Azure subscription, so it is not a cloud-readiness check.

### 2. Create the landing-zone story

Validate the metadata-only manifest, then create the synthetic landing layout:

```powershell
python -I scripts\demo_dataset_manifest.py
New-Item -ItemType Directory -Force -Path (Join-Path $demo 'landing') | Out-Null
python -I scripts\stage_demo_landing.py `
  --root (Join-Path $demo 'landing') `
  --inventory (Join-Path $demo 'landing-inventory.sqlite3')
```

Look for `verified: true`, `paths_preserved: true`, 34 placeholder files, and entries in `complete` state. These are generated placeholders and synthetic identities, not FASTQ contents or an instrument transfer. Ask the room what the manifest proves, then what it cannot prove about a real sender or share.

### 3. Follow one synthetic run

The reference build, immutable version, and manifest digest below are a matched set from the repository's synthetic reference contract. Keep all three explicit:

```powershell
python -m scripts.run_secondary_pipeline `
  --run-id SYN-SE-DEMO-001 `
  --work-dir (Join-Path $demo 'run-work') `
  --publish-dir (Join-Path $demo 'published') `
  --provenance-db (Join-Path $demo 'run-history.sqlite3') `
  --reference-build SYN-demo-genome `
  --reference-version synthetic-1385e2e921c4 `
  --reference-manifest-sha256 7e3be36672095e4018dfded5466ddb002848387e19d314595cb1a128a231be83
```

Inspect the JSON for `terminal_state: succeeded`, the same reference identity, and `provenance.output_uris`. The run generates a tiny synthetic sample at runtime. Its alignment and variant-calling stages are demonstration stubs, not validated bioinformatics; the results say nothing about accuracy on real sequencing data. See the [pipeline guide](secondary-pipeline.md) for the implementation boundary and Nextflow path.

Teaching prompt: "What would make this result reproducible?" Point to the run ID, workflow version, immutable reference identity, input/output URIs, and terminal state in provenance.

### 4. Make the safeguards visible

Run the synthetic failure rehearsal in its own state folder:

```powershell
$state = Join-Path $demo 'rehearsal-state'
New-Item -ItemType Directory -Force -Path $state | Out-Null
python scripts\rehearse_demo_failures.py --state-root $state
```

The report should say `all_passed: true` and `infrastructure_touched: false`. It rehearses a sender-declared failed transfer and retry, rejects a malformed variant row while retaining its reason, and denies an unauthorized read. Ask which step stops bad or unauthorized data from appearing as a successful result.

### 5. Close cleanly

Reset only the rehearsal's named local stores and landing folder:

```powershell
python scripts\reset_demo.py --state-root $state
python scripts\reset_demo.py --state-root $state --diagnose
```

Confirm `clean: true` and `infrastructure_touched: false`. This reset does not remove the separate pipeline outputs or every file under `$demo`; inspect your dedicated temporary folder before cleaning it up.

## Tell the story accurately

The local walkthrough shows two separate paths:

`metadata manifest → placeholder landing files → local inventory`

`pinned synthetic reference → generated reads → demonstration analysis → run provenance`

The placeholder landing files do not feed the secondary-analysis run. These independent harnesses teach the component contracts, not an integrated data path or an end-to-end Azure deployment. The local variant store, governed queries, and view models use SQLite and synthetic records. They are not a deployed Delta table, analytics workspace, SQL endpoint, dashboard, or governed AI service. AI-assisted analysis is exploratory, not a clinical determination.

For a customer-facing walkthrough, label each statement as **shown locally**, **partially demonstrated**, or **not yet accepted live**. Do not claim automatic compliance, clinical decision support, a released Microsoft product, or a confirmed customer deployment.

## If the audience wants Azure

Pause before provisioning. Azure deployments can create billable resources and require a current subscription preflight, an approved resource plan and cost limit, explicit authorization, compatible references, and a teardown plan. Follow the detailed [demo runbook](demo-runbook.md) and [infrastructure guide](../infra/README.md), not an improvised command from a slide.

The Slurm and AMLFS campaign is not yet accepted live, and no validated gallery image is claimed. Its local `validate` action does not contact Azure; its `run` action creates billable resources. Do not run it as part of this local walkthrough. See the [capability coverage](coverage.md) and [known limitations](limitations.md) for current evidence and blockers.
