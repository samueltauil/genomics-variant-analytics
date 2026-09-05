# Contributing

This is a demo accelerator for Microsoft solution engineers. There is no support commitment and no service level — see [README](README.md#support).

## Reporting a defect

Open an issue. Include:

- The commit you were on
- The phase you were in — preflight, provisioning, seeding, presentation, reset, teardown
- What you expected, from which spec or runbook step
- What happened, with the confirming observation that was missing
- Region and subscription type, without identifiers

If it blocked a customer delivery, say so. That changes the priority.

## Proposing a change

This repository is spec-driven. Behavior changes start in the specs, not in the code.

1. Read the relevant capability spec under [openspec/](openspec/)
2. Run `openspec` to create a change with a proposal, delta specs, design, and tasks
3. Open a pull request with the planning artifacts and the implementation together

If your change alters observable behavior and the spec does not move, the review will ask why.

## Ground rules

**No real data.** Synthetic or openly licensed only. No patient-identifiable content of any kind. A required check fails any pull request introducing `.vcf`, `.bam`, `.cram`, `.fastq`, or oversized files — do not work around it.

**No environment-specific values.** No subscription ids, tenant ids, author-specific resource names, or hostnames. Everything environment-bound is a parameter.

**No secrets.** Deployment authenticates through federated credentials. If you find yourself adding a client secret or storage key, the design is wrong.

**Claims are reviewed.** Changes to presenter-facing material get checked against [docs/claim-register.md](docs/claim-register.md). Confirmed and proposed items stay distinguishable — proposed items are labelled assumptions, not presented as design.

**Cite platform behavior.** If you assert what an Azure or GitHub feature does, link the documentation. Several corrections in [docs/limitations.md](docs/limitations.md) exist because an earlier draft asserted behavior that documentation contradicts.

## Pull requests

- One concern per pull request
- Say what you verified and how — every task in this repository carries a verification condition, and reviews expect the same
- Automated review runs first on workflow, container, manifest, and schema paths; a reference-build change without a version bump, or a schema change without a matching spec change, gets flagged

## Releases

`pipeline_version` on a variant record resolves to a release tag. Releases are immutable — tags lock to a commit, assets cannot be modified, and tag names cannot be reused. Publish from a draft with all assets attached.

Breaking that link breaks provenance for every variant produced by that pipeline.
