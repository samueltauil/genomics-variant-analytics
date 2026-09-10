# Local Landing Inventory

[scripts/scan_landing.py](../scripts/scan_landing.py) implements OpenSpec task 2.1:
scheduled directory scans with persistent file metadata. It needs Python 3.10+
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
and retained history. The database binds to the root and parsing pattern on first
use; a different root or pattern requires a different database.

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
`arrival_timestamp`, `last_seen_timestamp`, `metadata_error`, `state` and `present`.
Arrival is the UTC time of first observation, not filesystem creation time or
the exact transfer start. It persists through file growth and process restarts.
Missing files remain in history with `present: false`; their previous metadata
and timestamps are retained. `file_count` counts currently observed files only.

## Limits

All new files remain `arriving`. Reports state `completeness_evaluated: false`
and `azure_readiness: not-evaluated`. Stable-file/marker checks (2.2), failure and
retry transitions (2.3), staging and cloud scheduling are still pending. Do not
use this inventory as an authorization to stage data.

The scan reads metadata only. It does not open payloads, validate FASTQ contents,
calculate checksums or establish a coherent snapshot of concurrently changing
files. A traversal error discards that poll and leaves the prior snapshot intact.
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

The 12 tests generate tiny synthetic fixtures in temporary directories. They
verify required fields, scheduled discovery (with a controlled clock wait),
growth/restarts, custom and unmatched paths, missing files, database binding,
input guards, redirected entries, failed-scan preservation and the CLI. No
sequencing files or inventory databases are stored in repository fixtures.