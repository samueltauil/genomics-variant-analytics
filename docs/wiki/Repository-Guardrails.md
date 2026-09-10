# Repository Guardrails

**Observed on 2026-09-10.** Branch review and required checks protect the public code repository's `main` branch. Repository secret push protection also applies to supported patterns pushed to other branches. These are live GitHub settings, not settings inherited by cloning, forking, or editing its separate wiki.

## Installed Controls

| Control | Verified configuration |
|---|---|
| Required checks | `data-hygiene` and `hygiene-tests`, bound to GitHub Actions app ID `15368` |
| Up-to-date requirement | Strict required-status policy |
| Review | Zero required approvals, explicitly authorized by the maintainer on 2026-09-10 for solo development; PRs and required checks retained |
| Administrators | Classic branch protection enforced |
| Force pushes and deletion | Disabled for `main` |
| Additional PR rule | Active default-branch ruleset `22782462`, resolved review threads required, no bypass actors |
| Secret scanning and push protection | Both enabled before and after a live, no-bypass synthetic credential-pattern rejection test |

The PR author cannot self-approve. [PR #1](https://github.com/samueltauil/genomics-variant-analytics/pull/1) installed the workflows; [PR #10](https://github.com/samueltauil/genomics-variant-analytics/pull/10) holds the detailed acceptance record and remains pending review as of the date above.

## How the Gate Works

The privileged `pull_request_target` workflow checks out the trusted policy and fetches proposed commits only as Git objects. It does not check out or execute proposed code. It posts `data-hygiene` on the exact proposed head SHA. Proposed-code tests run in a separate read-only workflow.

The scanner rejects case-insensitive genomic extensions and their supported compressed forms, Git blobs larger than 1,048,576 bytes, and submodules it cannot inspect. The limit is inclusive: a 1,048,576-byte blob is not oversized. It inspects the head tree and all introduced commits, so a later deletion or rename does not erase a violation.

See the [scanner](https://github.com/samueltauil/genomics-variant-analytics/blob/main/scripts/check_data_hygiene.py), [trusted workflow](https://github.com/samueltauil/genomics-variant-analytics/blob/main/.github/workflows/data-hygiene.yml), and [tests](https://github.com/samueltauil/genomics-variant-analytics/blob/main/tests/test_data_hygiene.py) for the exact implementation.

## Live Acceptance Evidence

| Case | PR | Result |
|---|---|---|
| Empty commit, positive control | [#3](https://github.com/samueltauil/genomics-variant-analytics/pull/3) | Both required checks passed; administrator direct push rejected for missing independent approval |
| Zero-byte VCF file | [#4](https://github.com/samueltauil/genomics-variant-analytics/pull/4) | Required hygiene status failed; merge API returned HTTP 405 |
| Zero-byte BAM file | [#5](https://github.com/samueltauil/genomics-variant-analytics/pull/5) | Required hygiene status failed; merge API returned HTTP 405 |
| Zero-byte CRAM file | [#6](https://github.com/samueltauil/genomics-variant-analytics/pull/6) | Required hygiene status failed; merge API returned HTTP 405 |
| Zero-byte FASTQ file | [#7](https://github.com/samueltauil/genomics-variant-analytics/pull/7) | Required hygiene status failed; merge API returned HTTP 405 |
| 1,048,577 ASCII `x` characters | [#8](https://github.com/samueltauil/genomics-variant-analytics/pull/8) | Size limit failed; merge API returned HTTP 405 |
| Proposed scanner deletion plus zero-byte VCF | [#9](https://github.com/samueltauil/genomics-variant-analytics/pull/9) | Trusted scanner still rejected the VCF; merge API returned HTTP 405 |

The negative cases branched independently. No biological data or credentials were used, and no forbidden fixture was merged. Rule suite `4021920031` recorded the passing-head administrator push with status checks passing and the approval requirement failing. Rule suite `4021835591` recorded a fresh-commit direct-push refusal. Workflow run links are preserved in the acceptance record in PR #10; logs remain subject to GitHub retention.

During the initial zero-approval configuration, GitHub accepted the empty commit from the already-open, green [PR #2](https://github.com/samueltauil/genomics-variant-analytics/pull/2) as a fast-forward merge. Independent approval was then required and the probe repeated successfully. The maintainer subsequently authorized returning both review counts to zero to unblock solo implementation. Strict checks, the PR rule, administrator enforcement, resolved threads, no bypass actors and force-push/deletion restrictions were verified unchanged. The green-PR fast-forward gap therefore applies again; earlier rejection probes are historical evidence, not a current guarantee.

Test PRs #3-#9 are unmerged and their closure submissions were still pending at the last verification. They are intentional probes, not proposed product changes; do not approve or merge them.

## Secret Push Protection

Task 1.2 was verified at 15:21 UTC on 2026-09-10 by a repository administrator. Secret scanning and repository push protection were already enabled; no setting was changed. A harmless control push succeeded, then a locally constructed, never-issued PAT-shaped value was rejected with `GH013`, `GITHUB PUSH PROTECTION`, and `GitHub Personal Access Token`. GitHub reported the probe commit `0308f7ce791ca7aa43f87fcf69c2eced402347ae` and `synthetic-push-protection.txt:1` in the push response.

The remote stayed at harmless control commit `71ce48f5ee44c9b7e123be59208012a0c46f988a`. The disposable branch was deleted and its absence confirmed. No real credential was issued or used, no bypass was requested, and the fixture is not in the implementation history. The [redacted acceptance record](https://github.com/samueltauil/genomics-variant-analytics/blob/ae872112f936fc9e71621ab08f0fa7d70fb9c71e/CONTRIBUTING.md#secret-protection-acceptance-record-2026-09-10) includes the procedure, settings, commit IDs, and cleanup. [PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12) holds the record pending review.

Detection was verified in the push response, not a Security-tab alert. Public-repository user push protection may overlap; the test did not isolate those controls. Non-provider patterns and validity checks were disabled and were not tested.

## Limits of the Guarantee

- Genomic-file hygiene is merge-time enforcement. Unprotected branches and forks can already expose rejected data publicly.
- The scanner does not classify arbitrary patient text, inspect archive contents, or download LFS payloads. Renaming data to evade a check is prohibited.
- The file checker is not a credential scanner. GitHub push protection covers supported recognizable patterns, not every password or sensitive value; provider formats can change and explicit bypass flows exist. The no-bypass test does not prove bypass is impossible.
- Merge queues are not supported by the current workflow because it does not handle `merge_group` events.
- Code-repository branch protection is not a content gate on this wiki. Keep wiki editing restricted to trusted contributors and apply the same no-data/no-secrets rules.

## Sources

- [Acceptance record under review](https://github.com/samueltauil/genomics-variant-analytics/blob/3149606898f7eeffe8e22a1c05f494d0f4e4748f/CONTRIBUTING.md#live-acceptance-record-2026-09-10)
- [Default-branch ruleset](https://github.com/samueltauil/genomics-variant-analytics/rules/22782462)
- [GitHub guidance on pull_request_target](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target)
- [GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [Supported secret patterns](https://docs.github.com/en/code-security/secret-scanning/introduction/supported-secret-scanning-patterns)
- [Command-line push protection](https://docs.github.com/en/code-security/secret-scanning/working-with-secret-scanning-and-push-protection/working-with-push-protection-from-the-command-line)