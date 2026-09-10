# Repository Guardrails

**Observed on 2026-09-10.** These controls apply to the public code repository's `main` branch. They are live GitHub settings, not settings inherited by cloning, forking, or editing its separate wiki.

## Installed Controls

| Control | Verified configuration |
|---|---|
| Required checks | `data-hygiene` and `hygiene-tests`, bound to GitHub Actions app ID `15368` |
| Up-to-date requirement | Strict required-status policy |
| Review | One independent approving review from a reviewer with write access; stale approvals dismissed |
| Administrators | Classic branch protection enforced |
| Force pushes and deletion | Disabled for `main` |
| Additional PR rule | Active default-branch ruleset `22782462`, resolved review threads required, no bypass actors |

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

During the initial zero-approval configuration, GitHub accepted the empty commit from the already-open, green [PR #2](https://github.com/samueltauil/genomics-variant-analytics/pull/2) as a fast-forward merge. Independent approval was then required and the probe repeated successfully. This does not establish that GitHub forbids every fast-forward push satisfying an approved PR's requirements.

Test PRs #3-#9 are unmerged and their closure submissions were still pending at the last verification. They are intentional probes, not proposed product changes; do not approve or merge them.

## Limits of the Guarantee

- This is merge-time enforcement. Unprotected branches and forks can already expose rejected content publicly.
- The scanner does not classify arbitrary patient text, inspect archive contents, or download LFS payloads. Renaming data to evade a check is prohibited.
- The file checker is not a credential scanner. Secret scanning and push-protection acceptance belong to task 1.2 and remain unverified.
- Merge queues are not supported by the current workflow because it does not handle `merge_group` events.
- Code-repository branch protection is not a content gate on this wiki. Keep wiki editing restricted to trusted contributors and apply the same no-data/no-secrets rules.

## Sources

- [Acceptance record under review](https://github.com/samueltauil/genomics-variant-analytics/blob/3149606898f7eeffe8e22a1c05f494d0f4e4748f/CONTRIBUTING.md#live-acceptance-record-2026-09-10)
- [Default-branch ruleset](https://github.com/samueltauil/genomics-variant-analytics/rules/22782462)
- [GitHub guidance on pull_request_target](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target)
- [GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)