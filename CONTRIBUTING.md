# Contributing

This is a demo accelerator for Microsoft solution engineers. There is no
support commitment or SLA; see [SUPPORT.md](SUPPORT.md).

## Reporting a defect

Follow the defect-reporting route and sanitization requirements in
[SUPPORT.md](SUPPORT.md). If the defect blocked a customer delivery, say so in
the issue.

## Proposing a change

This repository is spec-driven. Behavior changes start in the specs, not in the code.

1. Read the relevant capability spec under [openspec/](openspec/)
2. Run `openspec` to create a change with a proposal, delta specs, design, and tasks
3. Open a pull request with the planning artifacts and the implementation together

If your change alters observable behavior and the spec does not move, the review will ask why.

## Ground rules

**No real data.** Synthetic or openly licensed only, kept outside Git. No patient-identifiable content of any kind. The data-hygiene workflow rejects genomic files and files over 1 MiB. It is a required merge gate on this repository's `main` branch; forks need their own administrator setup below. Do not work around it.

**No environment-specific values.** No subscription ids, tenant ids, author-specific resource names, or hostnames. Everything environment-bound is a parameter.

**No secrets.** Deployment authenticates through federated credentials. If you find yourself adding a client secret or storage key, the design is wrong.

**Claims are reviewed.** Changes to presenter-facing material get checked against [docs/claim-register.md](docs/claim-register.md). Confirmed and proposed items stay distinguishable — proposed items are labelled assumptions, not presented as design.

**Cite platform behavior.** If you assert what an Azure or GitHub feature does, link the documentation. Several corrections in [docs/limitations.md](docs/limitations.md) exist because an earlier draft asserted behavior that documentation contradicts.

## Pull requests

Current policy (2026-09-10): the maintainer authorized zero required approvals
to support solo development. PRs, strict passing checks, administrator
enforcement and resolved review threads remain required. Historical
independent-review and administrator direct-push rejection evidence below
describes the earlier configuration. A green, already-open PR head may again
allow an administrator fast-forward; no stronger direct-push guarantee is made.

- One concern per pull request
- Say what you verified and how — every task in this repository carries a verification condition, and reviews expect the same
- [Automated engineering review](docs/engineering-controls.md#automated-pull-request-review)
  runs first on workflow, container, manifest, and schema paths; a
  reference-build change without a version bump, or a schema change without a
  matching spec change, gets flagged

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

These are live GitHub settings, not settings activated by cloning this repository. This repository's configuration and acceptance results are recorded below; repeat setup and verification for a fork.

1. Confirm the repository is public before using this public-repository enforcement model. Review and land the scanner and workflows as a bootstrap change with no genomic files, then open a harmless pull request to produce the first `data-hygiene` status. The trusted policy must already exist on the default branch before it can inspect later pull requests.
2. Protect the default branch: require a pull request with at least one independent approving review from a reviewer with write access, dismiss stale approvals, require `data-hygiene` and `hygiene-tests` from the GitHub Actions app, require the branch to be up to date, disallow bypass (including administrators), and leave force pushes and branch deletion disabled. Add an active default-branch pull-request ruleset with the same approval requirement, resolved review threads, and no bypass actors. The PR author cannot approve their own change. Do not enable a merge queue: this workflow does not yet handle `merge_group` events. See [protected branch settings](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
3. Verify a harmless pull request passes its checks. In a disposable test repository with the same settings, use empty `.vcf`, `.bam`, `.cram`, and `.fastq` files and a generated non-sensitive 1,048,577-byte text file in separate pull requests to verify each status fails and merging is refused. Also test a pull request that deletes or disables the scanner while adding a forbidden file; the trusted check must still fail. Never use real genomic files for these tests.
4. In that test repository, verify a direct push of a harmless change to the protected default branch is refused, including for an administrator. Repeat with an unapproved PR head whose required checks already pass; a zero-approval policy can allow this push as a fast-forward PR merge. Record the status URLs, protection settings, actor role, and denial results before marking OpenSpec task 1.1 complete. Repeat the harmless checks on the target repository after installation.
5. Separately enable and verify secret scanning and push protection for OpenSpec task 1.2. The file checker is not a credential scanner. Follow [GitHub's push protection guidance](https://docs.github.com/en/code-security/secret-scanning/introduction/about-push-protection); do not generate or publish a real credential for testing.

**Enforcement point and gaps:** this public-repository design gates merging, not pushing to unprotected branches or forks. Rejected content may already be publicly visible there. Local ignore rules are only a convenience. The checker recognizes file names and Git blob sizes; it does not classify arbitrary patient text, inspect archive contents, or download LFS payloads. Renaming data to an unrelated extension is not allowed even where it evades this check. Never upload data to Git in the first place. Public repositories cannot use the private/internal push-ruleset substitute described in [the design](openspec/changes/add-genomics-variant-accelerator/design.md).

### Live acceptance record (2026-09-10)

Scope: the public `samueltauil/genomics-variant-analytics` repository, default branch `main`, tested by `samueltauil` with administrator permissions. [PR #1](https://github.com/samueltauil/genomics-variant-analytics/pull/1) installed the scanner and workflows. Classic protection requires strict, up-to-date `data-hygiene` and `hygiene-tests` checks bound to GitHub Actions (app ID `15368`), one independent approval, stale-review dismissal, and administrator enforcement; force pushes and deletion are disabled. Active [ruleset 22782462](https://github.com/samueltauil/genomics-variant-analytics/rules/22782462) additionally requires reviewed pull requests and resolved review threads on the default branch, with no bypass actors.

The initial zero-approval policy allowed a direct push of the already-open, passing [PR #2](https://github.com/samueltauil/genomics-variant-analytics/pull/2), which GitHub treated as a fast-forward merge. That PR contained only an empty commit; no file content changed. After requiring independent approval, [PR #3](https://github.com/samueltauil/genomics-variant-analytics/pull/3) passed both checks ([trusted run](https://github.com/samueltauil/genomics-variant-analytics/actions/runs/34491413490)), but the same administrator direct-push attempt was rejected. GitHub rule suite `4021920031` recorded status checks passing and the approval rule failing. A fresh commit without a PR was also refused (rule suite `4021835591`). These observations do not claim that GitHub forbids a fast-forward push that satisfies an approved PR's requirements.

Each negative probe branched independently from `1791e831b87af93999655c265641572e86c48b01`. Extension fixtures were zero bytes; the oversized blob was exactly 1,048,577 ASCII `x` characters. No biological data, patient identifiers, or credentials were used. Tests ran on isolated branches in this target repository, not a separate disposable repository.

| Probe | Pull request | Trusted workflow | Observed violation |
|---|---|---|---|
| Empty VCF | [#4](https://github.com/samueltauil/genomics-variant-analytics/pull/4) | [Run](https://github.com/samueltauil/genomics-variant-analytics/actions/runs/34491717429) | Genomic file extension |
| Empty BAM | [#5](https://github.com/samueltauil/genomics-variant-analytics/pull/5) | [Run](https://github.com/samueltauil/genomics-variant-analytics/actions/runs/34491723988) | Genomic file extension |
| Empty CRAM | [#6](https://github.com/samueltauil/genomics-variant-analytics/pull/6) | [Run](https://github.com/samueltauil/genomics-variant-analytics/actions/runs/34491728300) | Genomic file extension |
| Empty FASTQ | [#7](https://github.com/samueltauil/genomics-variant-analytics/pull/7) | [Run](https://github.com/samueltauil/genomics-variant-analytics/actions/runs/34491732681) | Genomic file extension |
| Oversized text | [#8](https://github.com/samueltauil/genomics-variant-analytics/pull/8) | [Run](https://github.com/samueltauil/genomics-variant-analytics/actions/runs/34491736958) | 1,048,577 bytes exceeds 1,048,576 bytes |
| Proposed scanner deletion plus empty VCF | [#9](https://github.com/samueltauil/genomics-variant-analytics/pull/9) | [Run](https://github.com/samueltauil/genomics-variant-analytics/actions/runs/34491742372) | Trusted base scanner still rejects extension |

All six head statuses failed, GitHub reported each PR as `BLOCKED`, and all six administrator merge API attempts returned HTTP 405. PRs #4-#8 explicitly named the failing required `data-hygiene` check; #9 reported both required checks failing because proposed-code tests also lost their scanner. Independent approval was additionally required. The protected `main` ref stayed at `1791e831b87af93999655c265641572e86c48b01` throughout these rejection tests, and no forbidden fixture was merged. Test-PR closure requests are awaiting interactive submission; the probes remain unmerged and must not be approved or merged. Workflow logs have GitHub's configured retention period.

Local verification: 12 synthetic repository tests pass, both workflows pass actionlint 1.7.12, and strict OpenSpec validation passes. This completes task 1.1's implementation and acceptance conditions. Secret push protection (task 1.2) and all Azure deployment work remain unverified.

## Secret scanning and push protection

GitHub repository secret scanning and push protection are separate from the file-name and size check. Both settings must be enabled under the repository's security settings. An administrator can inspect them without retrieving credentials:

```sh
gh api repos/OWNER/REPO --jq '.security_and_analysis | {secret_scanning, secret_scanning_push_protection}'
```

Both statuses must be `enabled`; settings alone do not prove push-time enforcement. See [GitHub's supported patterns](https://docs.github.com/en/code-security/secret-scanning/introduction/supported-secret-scanning-patterns) and [command-line push protection](https://docs.github.com/en/code-security/secret-scanning/working-with-secret-scanning-and-push-protection/working-with-push-protection-from-the-command-line).

### Administrator acceptance procedure

1. Use a disposable branch, never the default branch. Verify a harmless control push succeeds so authentication and branch restrictions cannot explain the negative result.
2. Construct a nonfunctional credential-shaped value locally, never issued by a provider or associated with an account. Use a currently supported push-protection pattern, including its format/checksum requirements. Do not obtain a real credential, read a credential from the environment, or use a published secret found elsewhere.
3. Put only the synthetic value in a disposable commit. Keep it out of the implementation branch, documentation, and logs. Push that commit to the same control branch and require an explicit secret-protection rejection naming the credential type, commit, and file location. An authentication error, branch-protection refusal, or local scanner failure is not a pass.
4. Do not follow the bypass link or allow the test value. Verify the remote branch still points to the harmless control commit, then delete the disposable remote branch and confirm its absence. Record the time, actor role, settings, commit IDs, redacted rejection, and cleanup result before completing task 1.2.

### Secret-protection acceptance record (2026-09-10)

Verified on `samueltauil/genomics-variant-analytics` at 15:21 UTC by a repository administrator. The REST API reported `secret_scanning.status` and `secret_scanning_push_protection.status` as `enabled` before the test; both were already enabled and required no settings change. Non-provider patterns and validity checks were disabled, so this record does not claim either feature was tested.

The test constructed a never-issued GitHub PAT-shaped value locally: a 30-character random Base62 payload and a six-character, zero-padded Base62 CRC32 checksum, following [GitHub's published token format](https://github.blog/engineering/platform-security/behind-githubs-new-authentication-token-formats/). The value was not obtained from an account, used for authentication, or printed. Only the disposable Git object contained the value; it is not part of this implementation branch. This tests recognition of a pattern, not validity of a credential.

| Observation | Result |
|---|---|
| Base `main` commit | `1791e831b87af93999655c265641572e86c48b01` |
| Disposable branch | `acceptance/secret-push-20260910-ef675937` |
| Harmless control commit | `71ce48f5ee44c9b7e123be59208012a0c46f988a`; push succeeded and remote SHA matched |
| Synthetic probe commit | `0308f7ce791ca7aa43f87fcf69c2eced402347ae`; only added `synthetic-push-protection.txt`, 41 bytes |
| Probe push | Exit 1, explicit `GH013` secret-protection rejection |
| Remote after rejection | Still the harmless control SHA; probe did not advance the branch |
| Cleanup | Remote branch deletion succeeded; `git ls-remote --heads` confirmed its absence |

Relevant server response, with the bypass URL omitted:

```text
GH013: Repository rule violations found
GITHUB PUSH PROTECTION
Push cannot contain secrets
GitHub Personal Access Token
commit: 0308f7ce791ca7aa43f87fcf69c2eced402347ae
path: synthetic-push-protection.txt:1
```

No bypass was requested and no pull request was opened for the probe. Detection was reported in the push response; a Security-tab alert was not verified for this rejected, unbypassed push. Public-repository user push protection can also apply, so the test records repository settings and the observed rejection without isolating those overlapping controls. A local pre-push fixture assertion initially caught Windows newline conversion in Git tree input; byte-exact subprocess input corrected it before the credential-shaped commit was pushed. The same harmless control branch was reused and then removed. The rejection above, not that local assertion, is the acceptance evidence. Rejected commits and deleted test branches are not durable public evidence links; the redacted transcript and commit IDs are recorded here for review.

**Limits:** push protection covers recognized supported patterns, not every password or arbitrary sensitive text. Provider formats and coverage can change. GitHub offers explicit bypass flows; a successful no-bypass test does not prove bypass is impossible. The genomic-file control remains merge-time enforcement. For an actual leaked credential, revoke or rotate it and remove it from all affected commits; deleting only the latest file does not remove the secret from history.

## Releases

`pipeline_version` on a variant record resolves to a release tag. Releases are immutable — tags lock to a commit, assets cannot be modified, and tag names cannot be reused. Publish from a draft with all assets attached.

Breaking that link breaks provenance for every variant produced by that pipeline.
