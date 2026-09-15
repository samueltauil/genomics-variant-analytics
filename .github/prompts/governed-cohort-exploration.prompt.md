---
description: "Design a governed, build-aware cohort exploration query using synthetic data"
---

Answer this cohort exploration request:

`${input:question:Describe the cohort or variant question}`

Reference selection:

`${input:reference:Provide the reference build and immutable version or manifest digest}`

Use the repository specs and exact variant-store schema. Produce a query plan or query only for the governed analytics interface; do not request or expose raw table credentials, storage credentials, or direct genomic-file access.

The available variant fields are exactly:

- VCF core: `CHROM`, `POS`, `ID`, `REF`, `ALT`, `QUAL`, `FILTER`, `INFO`
- Accelerator context: `sample_id`, `research_subject_id`, `cohort_id`, `gene`, `transcript`, `variant_consequence`, `genotype`, `allele_frequency`, `reference_build`, `pipeline_version`, `source_file_uri`, `ingestion_timestamp`

Requirements:

- Require the caller's access tier and withhold subject linkage for de-identified access.
- Require an explicit reference build and immutable version or manifest digest. Fail rather than infer or default it.
- Keep records from different builds separate unless a documented, versioned liftover is explicitly requested.
- Use only the exact schema fields. If the question needs an absent field, identify the schema gap rather than inventing a column.
- Use synthetic identifiers and synthetic cohort or clinical attributes in examples. Include no PHI or customer data.
- Return source file URI, producing run, reference build, pipeline version, and store version or snapshot for traceability and reproducibility.
- Label the result as exploratory and not a diagnosis, clinical determination, treatment recommendation, or compliance assessment.
- Distinguish demonstrated behavior from specified-only behavior when describing repository capabilities.
