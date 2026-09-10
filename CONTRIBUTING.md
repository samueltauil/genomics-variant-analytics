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

**No real data.** Synthetic or openly licensed only, kept outside Git. No patient-identifiable content of any kind. The data-hygiene workflow rejects genomic files and files over 1 MiB. It becomes a merge gate only after the repository administrator completes the setup below. Do not work around it.

**No environment-specific values.** No subscription ids, tenant ids, author-specific resource names, or hostnames. Everything environment-bound is a parameter.

**No secrets.** Deployment authenticates through federated credentials. If you find yourself adding a client secret or storage key, the design is wrong.

**Claims are reviewed.** Changes to presenter-facing material get checked against [docs/claim-register.md](docs/claim-register.md). Confirmed and proposed items stay distinguishable — proposed items are labelled assumptions, not presented as design.

**Cite platform behavior.** If you assert what an Azure or GitHub feature does, link the documentation. Several corrections in [docs/limitations.md](docs/limitations.md) exist because an earlier draft asserted behavior that documentation contradicts.

## Pull requests

- One concern per pull request
- Say what you verified and how — every task in this repository carries a verification condition, and reviews expect the same
- Automated review runs first on workflow, container, manifest, and schema paths; a reference-build change without a version bump, or a schema change without a matching spec change, gets flagged

## Data-hygiene check

Requires Git and Python 3.10 or newer; no Python packages are needed. Run from the repository root:

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python -I scripts/check_data_hygiene.py --head HEAD
python -I scripts/check_data_hygiene.py --base origin/main --head HEAD
```

Replace `origin/main` with the actual target branch. The check reads committed Git objects, not staged, untracked, or working-copy files. With `--base`, it checks the head tree and every introduced commit, so adding a forbidden file and deleting or renaming it in a later commit still fails. Failures report the path, commit, and reason without printing file contents. Exit codes are 0 for pass, 1 for policy violations, and 2 when inspection cannot complete.

The limit is 1,048,576 bytes per Git blob, inclusive. `--max-bytes` sets a different limit for a local invocation; the server uses the limit in the trusted workflow. Changing server policy requires a reviewed change to that workflow. Genomic extensions match case-insensitively: `.vcf`, `.gvcf`, `.bam`, `.bai`, `.cram`, `.crai`, `.sam`, `.fastq`, `.fq`, `.bcl`, `.fasta`, `.fa`, and `.2bit`, including compressed forms ending in `.gz`, `.bgz`, `.bz2`, `.xz`, `.zst`, or `.zip`. Submodules are rejected because their contents cannot be inspected as repository blobs.

The [data-hygiene workflow](.github/workflows/data-hygiene.yml) runs on `pull_request_target`, executes only the trusted policy, and fetches proposed commits as Git objects without checking out or executing their code. It posts a `data-hygiene` commit status on the exact pull-request head SHA. The job grants only repository read and commit-status write permissions; checkout does not persist credentials and the scanner step is not given a token. Tests of proposed code run separately with read-only permissions. See [GitHub's event security guidance](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target).

### Administrator setup and acceptance

These are live GitHub settings, not settings activated by cloning this repository. Their configuration and acceptance tests are still pending.

1. Confirm the repository is public before using this public-repository enforcement model. Review and land the scanner and workflows as a bootstrap change with no genomic files, then open a harmless pull request to produce the first `data-hygiene` status. The trusted policy must already exist on the default branch before it can inspect later pull requests.
2. Protect the default branch: require a pull request, require `data-hygiene` from the GitHub Actions app, require the branch to be up to date, disallow bypass (including administrators), and leave force pushes and branch deletion disabled. Review policy/workflow changes before merging. Do not enable a merge queue: this workflow does not yet handle `merge_group` events. See [protected branch settings](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
3. Verify a harmless pull request passes. In a disposable test repository with the same settings, use empty `.vcf`, `.bam`, `.cram`, and `.fastq` files and a generated non-sensitive 1,048,577-byte text file to verify the status fails and merging is refused. Also test a pull request that changes the scanner to return success while adding a forbidden file; the trusted check must still fail. Never use real genomic files for these tests.
4. In that test repository, verify a direct push of a harmless change to the protected default branch is refused, including for an administrator. Record the status URLs, protection settings, actor role, and denial results before marking OpenSpec task 1.1 complete. Repeat the harmless checks on the target repository after installation.
5. Separately enable and verify secret scanning and push protection for OpenSpec task 1.2. The file checker is not a credential scanner. Follow [GitHub's push protection guidance](https://docs.github.com/en/code-security/secret-scanning/introduction/about-push-protection); do not generate or publish a real credential for testing.

**Enforcement point and gaps:** this public-repository design gates merging, not pushing to unprotected branches or forks. Rejected content may already be publicly visible there. Local ignore rules are only a convenience. The checker recognizes file names and Git blob sizes; it does not classify arbitrary patient text, inspect archive contents, or download LFS payloads. Renaming data to an unrelated extension is not allowed even where it evades this check. Never upload data to Git in the first place. Public repositories cannot use the private/internal push-ruleset substitute described in [the design](openspec/changes/add-genomics-variant-accelerator/design.md).

## Releases

`pipeline_version` on a variant record resolves to a release tag. Releases are immutable — tags lock to a commit, assets cannot be modified, and tag names cannot be reused. Publish from a draft with all assets attached.

Breaking that link breaks provenance for every variant produced by that pipeline.
