# Demo dataset manifest

The committed [manifest](../demo/dataset-manifest.json) is metadata only. It
references the Illumina Platinum Genomes `2017-1.0` public sample distribution
in Azure Open Datasets; it does not copy, embed, or commit VCF, GVCF, BAM, CRAM,
FASTQ, or other genomic payloads. Source use remains subject to the terms linked
from the source catalog.

The source coordinate namespace is explicit: reference build `GRCh38` and
immutable source version `2017-1.0/hg38`. This records source provenance; it
does not declare the collection compatible with a workflow or a locally
published reference. The submission gate must validate an exact compatible
reference version or manifest digest before compute is allocated. No build may
be inferred or substituted.

## Synthetic identities

The generator creates only these identity fields:

| Field | Required pattern |
|---|---|
| `subject_id` | `^SYN-PG-SUBJECT-[0-9]{4}$` |
| `sample_id` | `^SYN-PG-SAMPLE-[0-9]{4}$` |
| `cohort_id` | `^SYN-PG-COHORT-[0-9]{2}$` |

The committed manifest contains 17 deterministic synthetic subject/sample
bindings split across two synthetic demo cohorts. These identifiers are not
the source collection's donor labels and must not be used to infer or
reconstruct them. Cohort membership is generated demo context with no clinical
meaning.

## Generate and validate

```powershell
python -I scripts\demo_dataset_manifest.py --write
python -I scripts\demo_dataset_manifest.py
python -m unittest tests.test_demo_dataset_manifest -v
```

Validation is fail closed. The manifest has an exact schema with no free-form
identity or clinical fields. The validator rejects unknown fields, common
patient-identifying field names, email addresses, US Social Security and phone
number forms, public donor-style identifiers, malformed or duplicate synthetic
IDs, credential-bearing source URIs, and missing or altered source/reference
provenance. A successful report states zero patient-identifying fields and
values and confirms that every subject ID matches the documented pattern.

This proves the committed metadata contract and generated identities, not the
contents or continued availability of the remote source collection. Download,
integrity verification, and workflow/reference compatibility remain separate
governed steps. The dataset is for this demo solution accelerator and is not
patient data or a clinical dataset.

## Stage the metadata-only landing layout

The staging harness derives one paired-end file name for every manifest identity
and places generated placeholder bytes under the instrument-style layout
`SYN-RUN-001/Data/Intensities/BaseCalls`. The placeholders are not FASTQ
content, are created only in the caller-supplied landing directory, and must
never be committed. The harness runs the existing scanner twice and fails
unless every manifest-defined relative path is observed unchanged and reaches
`complete`.

```powershell
New-Item -ItemType Directory -Force $env:TEMP\synthetic-landing | Out-Null
python -I scripts\stage_demo_landing.py `
  --root $env:TEMP\synthetic-landing `
  --inventory $env:TEMP\synthetic-landing-inventory.sqlite3
```

The JSON report includes the manifest and explicit `GRCh38` / `2017-1.0/hg38`
reference identity, the generated file count, and the scanner records. This is
a local metadata-only staging verification, not a download of the authorized
source collection or an Azure Files acceptance test.
