## Purpose

Provides the primary-analysis landing zone where sequencers and lab applications write output over SMB, so that genomics data enters Azure without any change to instrument configuration, folder conventions, or naming.

## ADDED Requirements

### Requirement: Unchanged sequencer write path

The landing zone SHALL accept sequencer output over SMB using the instrument's existing share path, folder hierarchy, and file naming conventions. No change to instrument configuration, vendor software, or lab operating procedure SHALL be required to write into the landing zone.

#### Scenario: Instrument writes using its existing convention

- **WHEN** a sequencer configured with an existing run-output folder convention writes to the landing-zone share
- **THEN** the files are stored under that same folder hierarchy with their original names
- **AND** no reconfiguration of the instrument is performed

#### Scenario: Lab application reads back a written file

- **WHEN** a lab application that expects SMB semantics opens a file it previously wrote to the landing zone
- **THEN** the file is readable through the same path with unchanged content

### Requirement: High-throughput sequential write support

The landing zone SHALL support the large-file, high-throughput sequential I/O profile produced by sequencing runs, and SHALL accept individual files at the sizes typical of FASTQ output without requiring the writer to split them.

#### Scenario: Large run output is written in a single pass

- **WHEN** a sequencing run writes a multi-gigabyte FASTQ file in a single sequential stream
- **THEN** the write completes without the landing zone rejecting the file for size
- **AND** the stored file size and content match what was written

### Requirement: File arrival visibility

The landing zone SHALL expose, for each landed file, the run and sample identifiers derivable from its path or name, its size, its arrival timestamp, and its current state (arriving, complete, failed).

#### Scenario: Operator inspects newly arrived files

- **WHEN** a laboratory operations manager reviews the landing zone for a given sequencing run
- **THEN** each file of that run is listed with its sample identifier, size, arrival timestamp, and state

#### Scenario: File is still being written

- **WHEN** a file transfer from the instrument is in progress
- **THEN** the file's state is reported as arriving and not complete
- **AND** downstream staging does not treat it as ready

### Requirement: Transfer failure detection and retry

The landing zone SHALL detect incomplete or failed transfers and SHALL make the failure visible with the affected run, sample, and file. A failed transfer SHALL be retryable without deleting or renaming previously landed files of the same run.

#### Scenario: Transfer is interrupted

- **WHEN** an instrument transfer is interrupted before the file is complete
- **THEN** the file is marked failed rather than complete
- **AND** it is excluded from downstream staging

#### Scenario: Operator retries a failed transfer

- **WHEN** the operator re-sends a file that previously failed
- **THEN** the retried file replaces the failed entry and is marked complete
- **AND** other files in the same run are unaffected

### Requirement: Ingestion boundary separation

The landing zone SHALL be the ingestion boundary only. Secondary analysis, variant processing, and analytics workloads SHALL NOT read directly from the landing zone; they SHALL consume data from object storage after staging.

#### Scenario: Analytics workload attempts direct access

- **WHEN** a downstream analytics or pipeline workload is granted access to project data
- **THEN** its access is to the staged object-storage location, not the SMB landing zone

### Requirement: Synthetic demo data only

Demonstration and accelerator content SHALL use synthetic or authorized sample files only. Real patient-identifiable sequencing data SHALL NOT be used in demo or sample datasets.

#### Scenario: Demo dataset is prepared

- **WHEN** a demo landing-zone dataset is assembled
- **THEN** every file is synthetic or an explicitly authorized sample
- **AND** no real patient identifiers are present
