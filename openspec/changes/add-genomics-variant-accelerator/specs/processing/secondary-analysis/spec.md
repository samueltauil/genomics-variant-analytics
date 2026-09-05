## Purpose

Turns staged sequencing reads into aligned and variant-oriented outputs by running a portable bioinformatics pipeline on elastic Azure compute, capturing enough provenance for every run to be reproduced and audited.

## ADDED Requirements

### Requirement: FASTQ to VCF pipeline stages

Secondary analysis SHALL execute, at minimum, quality control, read alignment against a selected reference genome, aligned-read output as BAM or CRAM, and variant calling producing VCF or GVCF. Each stage SHALL record its completion state and output locations.

#### Scenario: Pipeline completes end to end

- **WHEN** a run is submitted with staged FASTQ inputs and a selected reference build
- **THEN** quality control, alignment, and variant calling execute in order
- **AND** BAM/CRAM and VCF/GVCF outputs are produced with recorded output locations

#### Scenario: A stage fails

- **WHEN** any pipeline stage fails
- **THEN** the run is marked failed with the failing stage identified
- **AND** partial outputs are not published as complete pipeline results

### Requirement: Interchangeable execution targets

The pipeline SHALL be executable on either an elastic batch compute pool or an HPC cluster, and switching between the two SHALL NOT change the pipeline's outputs for the same inputs, reference build, and workflow version.

#### Scenario: Same run on batch and HPC

- **WHEN** the same inputs, reference build, and workflow version are executed on the batch target and on the HPC target
- **THEN** both produce equivalent BAM/CRAM and VCF/GVCF outputs
- **AND** both record the execution target used

#### Scenario: Neither target is presented as universally preferred

- **WHEN** the accelerator documents execution options
- **THEN** batch and HPC are presented as alternative targets with their applicable conditions, not as a single recommended default

### Requirement: Portable workflow definition

The pipeline SHALL be defined in a portable workflow language executable by a standard workflow engine, so that customers already running such engines can adopt the pipeline without rewriting it.

#### Scenario: Customer runs the workflow on an existing engine

- **WHEN** a customer executes the accelerator's workflow definition on their existing workflow engine
- **THEN** the workflow runs without requiring the definition to be rewritten for Azure

### Requirement: Run provenance capture

Every pipeline run SHALL record the workflow identifier and version, the reference build identifier and version, the execution target and compute pool, the input artifact URIs, the output artifact URIs, start and end timestamps, the terminal state, and the log location.

#### Scenario: Run provenance is queried

- **WHEN** a bioinformatics engineer requests the provenance of a completed run
- **THEN** workflow version, reference build, execution target, inputs, outputs, timings, state, and log location are returned

#### Scenario: Failed run retains provenance

- **WHEN** a run fails
- **THEN** its provenance record is retained with the terminal failure state and log location

### Requirement: Reproducible re-execution

Re-executing a run with the same inputs, workflow version, and reference build SHALL produce equivalent variant outputs, and the re-execution SHALL be recorded as a distinct run linked to the original.

#### Scenario: Reprocessing after a pipeline change

- **WHEN** a sample is reprocessed with a new workflow version
- **THEN** a new run record is created linked to the prior run for the same sample
- **AND** both runs remain independently resolvable

### Requirement: Elastic compute allocation

Compute for pipeline execution SHALL be allocated on demand for the duration of the workload and released afterwards, so that bursty sequencing throughput does not require permanently provisioned capacity.

#### Scenario: Burst of runs is submitted

- **WHEN** multiple runs are submitted concurrently
- **THEN** compute capacity is allocated to service them
- **AND** capacity is released once the runs reach a terminal state
