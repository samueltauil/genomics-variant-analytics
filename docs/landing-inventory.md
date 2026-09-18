# Local Landing Inventory

[scripts/scan_landing.py](../scripts/scan_landing.py) implements OpenSpec tasks 2.1,
2.2 and 2.3: scheduled directory scans with persistent metadata, completeness
classification, and failure/retry classification against a declared transfer
manifest. It needs Python 3.10+
and only the standard library. No Azure credentials, SDK, cloud scheduler or SMB
connection is used. The implementation is local and has not been deployed.

## Run

Supply an existing trusted local landing directory and a SQLite path outside it,
whose parent already exists. Both paths must be absolute. For example, with an
existing synthetic run under the indicated temporary directory:

```powershell
python scripts/scan_landing.py --root "$env:TEMP\synthetic-landing" --inventory "$env:TEMP\landing-inventory.sqlite3"
python scripts/scan_landing.py --root "$env:TEMP\synthetic-landing" --inventory "$env:TEMP\landing-inventory.sqlite3" --polls 3 --interval-seconds 60
```

One scan is the default. Repeated polling waits the specified positive number
of seconds after each scan before starting the next. There is no wait after the
last scan and no installed background service. Interrupt with Ctrl+C. A failed
scan stops the process with a nonzero exit status; completed prior polls remain
committed. Use one polling process per inventory.

Each successful scan emits one JSON line containing the current observations
and retained history. The database binds to the root, parsing pattern and optional
marker template on first use; a different configuration requires a different
database. Existing task 2.1 databases are upgraded in place with markers disabled.

## Path And Metadata Contract

The default pattern recognizes paired-end FASTQ paths such as:

```text
SYN-RUN-001/Data/Intensities/BaseCalls/SYN-SAMPLE-001_S1_L001_R1_001.fastq.gz
```

This produces run `SYN-RUN-001` and sample `SYN-SAMPLE-001`. It accepts any
intermediate directories, read 1 or 2, and `.fastq` with optional `.gz`.
Use `--path-pattern` with a Python regex containing named `run_id` and `sample_id`
groups for another instrument convention. Patterns match the entire relative
path with `/` separators; they do not rename or move source files. Patterns are
trusted configuration, not untrusted input.

Every regular file is listed, including unmatched names. Unmatched files have
null identifiers and `metadata_error: unrecognized-path`; IDs are not invented.
Each record contains `path`, `run_id`, `sample_id`, `size_bytes`, `modified_ns`,
`arrival_timestamp`, `last_seen_timestamp`, `metadata_error`, `state`, `present`,
`failure_reason`, `unchanged_since` and `declared_size_bytes`.
Arrival is the UTC time of first observation, not filesystem creation time or
the exact transfer start. It persists through file growth and process restarts.
Missing files remain in history with `present: false`; their previous metadata
and timestamps are retained. `file_count` counts currently observed files only.

## Completeness

A recognized file is `complete` when its size and nanosecond modification time
match the preceding successful poll and it was present in that poll. Otherwise
it is `arriving`. A later change revokes completeness; disappearance and
reappearance require a new stability pair. Unknown identifiers never become
complete. Reports use schema version 2 and `completeness_evaluated: true`.

Alternatively, configure a vendor marker through a root-relative template:

```powershell
python scripts/scan_landing.py --root "$env:TEMP\synthetic-landing" --inventory "$env:TEMP\marker-inventory.sqlite3" --completion-marker '{run_id}/RTAComplete.txt'
```

This example is opt-in, not an assumed instrument contract. Templates accept
`{run_id}`, `{sample_id}` and `{path}` without format modifiers. A marker must be
an observed regular file, distinct from the payload, with mtime at least as new
as that payload. Marker contents are not interpreted. Markers are never eligible
payloads themselves. Absolute paths, traversal, redirects and unknown fields
are rejected. A missing or stale marker does not bypass stability checking.

## Failure Detection And Retry

Stability alone cannot separate a finished transfer from a truncated one, so a
file is only classified `failed` against a size the sending run declared in
advance. Point the scanner at a root-relative manifest template and a stall
deadline in seconds:

```powershell
python scripts/scan_landing.py --root "$env:TEMP\synthetic-landing" --inventory "$env:TEMP\failure-inventory.sqlite3" --transfer-manifest '{run_id}/transfer-manifest.json' --stall-seconds 900
```

The template must use `{run_id}` exactly once so a manifest is still found when
none of its files arrived. Each manifest is a JSON object with exactly `run_id`
and `files`, where every entry has exactly `path` and `size_bytes`:

```json
{
  "run_id": "SYN-RUN-001",
  "files": [
    {
      "path": "SYN-RUN-001/Data/Intensities/BaseCalls/SYN-SAMPLE-001_S1_L001_R1_001.fastq.gz",
      "size_bytes": 209715200
    }
  ]
}
```

`run_id` must match the run in the manifest's own path, and a manifest may only
declare paths under that run, never itself and never a duplicate. Manifests over
1 MiB, unparsable manifests and absent manifests are rejected rather than
guessed. A rejected or missing manifest is reported in `manifest_errors`, and the
run's files are held at `arriving` with `metadata_error: manifest-unavailable` —
they are never advanced to `complete` on stability alone.

`unchanged_since` records when the current size and modification time were first
seen. Against a declared size:

| Observation | State | `failure_reason` |
| --- | --- | --- |
| Larger than declared | `failed` | `size-exceeds-declared` |
| Smaller than declared, unchanged past the deadline | `failed` | `incomplete-transfer` |
| Smaller than declared, within the deadline | `arriving` | none |
| Declared but never observed, past the deadline | `failed` | `missing-transfer` |
| Equal to declared | `complete` once stable or marked | none |

Declared files that never arrive are listed with `present: false` and the run and
sample identifiers their declared path resolves to, so the failure names the
affected run, sample and file.

Retry needs no separate command. A re-sent file changes size or modification
time, which resets `unchanged_since`, clears `failure_reason` and returns the
existing record to `arriving`; it becomes `complete` once it reaches the declared
size and stabilizes. The record is revised in place, so the retry replaces the
failed entry and keeps the original `arrival_timestamp`. Sibling files of the
same run are evaluated independently and are not disturbed. A re-send that
restarts from zero bytes is a size change, not a new failure.

Only `complete` files may be staged; `available_for_staging` returns exactly
those, so `arriving` and `failed` files are withheld. The scanner still reads no
payload: the declared size is compared against file metadata, and content
integrity is verified later by the staging checksum comparison.

## Limits

Two unchanged observations are a heuristic, not proof of transfer success: a
writer can pause or leave a truncated file. Without a transfer manifest the
scanner therefore classifies no failure at all and reports
`failure_detection: not-evaluated`. With a manifest, the guarantee is only as
good as the declaration: the scanner trusts that the declared size is the
intended size, and a sender that declares the truncated size it actually shipped
will be believed. Manifest authenticity, marker authenticity and instrument
clock behavior are outside this check, as is any content-level corruption that
preserves size. The stall deadline is deployment-specific and must exceed the
slowest legitimate pause in a healthy transfer; too short a deadline fails live
transfers. Staging and cloud scheduling remain pending. Do not use this inventory
as an authorization to stage data; `azure_readiness` stays `not-evaluated`.

The scan reads payload metadata only. It opens no sequencing file, does not
validate FASTQ contents, calculates no checksum and does not establish a coherent
snapshot of concurrently changing files. The only bytes it reads are those of a
configured transfer manifest, which is bounded at 1 MiB and parsed as strict
JSON. A traversal error discards that poll and leaves the prior snapshot intact.
The inventory is held in memory during a poll; large-scale performance is untested.

UNC/device paths, Windows non-fixed drives, and symlinks/reparse points are
rejected, including redirected ancestors. Only trusted local directories are
supported; this is not a sandbox against path races or every POSIX mount type.
Protect the database and stdout as metadata: names can contain sensitive values.
Use synthetic data only, keep state outside the repository, and do not commit
generated inventories. SQLite state and sidecars with `.sqlite3` names are ignored.

## Verification

```powershell
python -m unittest discover -s tests -p 'test_landing_scan.py' -v
```

The 32 tests generate tiny synthetic fixtures in temporary directories. They
verify required fields, scheduled discovery (with a controlled clock wait),
growth/restarts, custom and unmatched paths, missing files, database binding,
input guards, redirected entries, failed-scan preservation, slow writes,
mtime-only changes, vendor markers, transfer-manifest validation, truncated and
absent transfers, retry, sibling independence, staging exclusion and the CLI. No
sequencing files or inventory databases are stored in repository fixtures.