# Development Guide

The current executable surface is repository data hygiene. There is no application server, infrastructure deployment command, or end-to-end demo command yet.

## Local Checks

Use Git and Python 3.10 or newer. The scanner and tests use the standard library; no Python packages are required. From the repository root:

```sh
python -m unittest discover -s tests -p 'test_*.py' -v
python -I scripts/check_data_hygiene.py --head HEAD
python -I scripts/check_data_hygiene.py --base origin/main --head HEAD
```

Fetch the current target branch before the comparison and substitute it for `origin/main` when needed. The scanner reads committed Git objects, not staged or untracked files. A clean working copy does not prove introduced history is clean.

| Exit code | Meaning |
|---|---|
| `0` | Inspection completed without policy violations |
| `1` | A policy violation was found |
| `2` | Inspection could not complete; do not treat this as a pass |

The documented baseline is 12 passing synthetic Git-repository tests and actionlint 1.7.12 validation of both workflows. Fixtures must never contain biological data, real identifiers, or credentials.

## OpenSpec Workflow

The active change is `add-genomics-variant-accelerator`, using the `spec-driven` schema and repository-local planning artifacts. With OpenSpec available:

```sh
openspec status --change add-genomics-variant-accelerator --json
openspec instructions apply --change add-genomics-variant-accelerator --json
openspec validate add-genomics-variant-accelerator --strict
```

1. Read the relevant requirement, scenario, design decision, and task acceptance condition.
2. Implement the smallest testable change and add focused verification.
3. Record observations, not just commands. A successful local test does not establish a live service or repository control.
4. Mark a task complete only when every specified implementation and acceptance condition is verified. Leave blocked tasks unchecked and state the missing evidence.
5. Submit reviewed changes through a PR and keep the implementation, specs, and documentation coherent.

Do not archive the entire change because individual tasks are complete. Task 1.1's live acceptance record is in [PR #10](https://github.com/samueltauil/genomics-variant-analytics/pull/10); task 1.2's secret-protection record is in [PR #12](https://github.com/samueltauil/genomics-variant-analytics/pull/12). Both are pending review as of 2026-09-10. Two of 89 tasks are verified; all other tasks remain unverified. Default-branch task checkboxes remain stale until the evidence merges.

## Practical Lessons

- A forbidden file still fails when deleted or renamed in a later introduced commit. Remove prohibited content from the proposed history rather than disguising it.
- Stemless filenames such as `.vcf` need explicit coverage; Python path suffix parsing alone does not identify them reliably.
- For generated Git-tree tests on Windows, write byte-exact stdin with explicit line endings. PowerShell text pipelines can append a carriage return to a filename passed to `git mktree`.
- Test an administrator push of a passing but unapproved PR head. A zero-approval policy allowed a green, already-open PR to fast-forward during initial acceptance.

## Maintaining the Wiki

The Markdown sources are under `docs/wiki` in the code repository. `Home.md` is the landing page; `_Sidebar.md` supplies navigation. Links without file extensions name wiki pages. Keep the sources reviewable through code-repository PRs; the wiki's Git history is separate and its direct edits do not pass through this repository's required checks.

GitHub must have an initial wiki page before its separate Git remote is available. Once `Home` has been created in the signed-in web UI:

```sh
git clone https://github.com/samueltauil/genomics-variant-analytics.wiki.git
```

Review existing wiki pages before copying approved Markdown sources into that clone, then commit and push using the wiki's existing default branch. Do not replace unrelated pages or force-push its history. Verify the rendered Home page, sidebar, internal links, and diagrams after publication. No automatic synchronization workflow is installed.

When adding knowledge, state whether it is observed, specified, or unresolved. Include a date for live state and a link to its source or acceptance evidence. Do not put secrets, genomic data, environment identifiers, unsupported customer claims, or clinical conclusions in either Git repository.

## Sources

- [Contributing guide](https://github.com/samueltauil/genomics-variant-analytics/blob/main/CONTRIBUTING.md)
- [Task list](https://github.com/samueltauil/genomics-variant-analytics/blob/main/openspec/changes/add-genomics-variant-accelerator/tasks.md)
- [Repository Guardrails](Repository-Guardrails)