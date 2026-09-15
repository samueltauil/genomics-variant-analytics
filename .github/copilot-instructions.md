# Genomics variant accelerator instructions

Use these rules for every change, review, explanation, query, and generated example in this repository.

## Sources of truth

- Treat `openspec/changes/add-genomics-variant-accelerator/specs/variant-store/delta-variant-store/spec.md` as the schema contract.
- Treat `openspec/changes/add-genomics-variant-accelerator/specs/reference-data/reference-management/spec.md` as the reference-data contract.
- Treat `openspec/changes/add-genomics-variant-accelerator/specs/governance/access-and-lineage/spec.md` and `docs/claim-register.md` as the governance and positioning contracts.
- Preserve the distinction between confirmed requirements and items labelled as assumptions. Do not present an assumption as implemented or validated.

## Exact variant-store schema

The current Bronze variant record has exactly these eight VCF core fields:

`CHROM`, `POS`, `ID`, `REF`, `ALT`, `QUAL`, `FILTER`, `INFO`

It also has exactly these twelve accelerator context fields:

`sample_id`, `research_subject_id`, `cohort_id`, `gene`, `transcript`, `variant_consequence`, `genotype`, `allele_frequency`, `reference_build`, `pipeline_version`, `source_file_uri`, `ingestion_timestamp`

`CHROM`, `POS`, `REF`, and `ALT` are mandatory. Reject a record that lacks one of them. Record unavailable annotations or other non-derivable optional values as null; never fabricate them.

Do not add, rename, remove, or repurpose a variant-store field merely to satisfy an implementation request. First identify the schema impact and require the corresponding OpenSpec schema contract to change in the same reviewed change. Keep ingestion, rejected-record handling, queries, visualizations, documentation, and tests aligned with the contract.

## Synthetic data and PHI

- Use synthetic identifiers and synthetic clinical or cohort attributes in examples, fixtures, prompts, tests, and demos.
- Never add real patient identifiers, protected health information, customer data, or customer names. Fields such as patient name, MRN, date of birth, address, or direct contact details do not belong in the accelerator schema.
- Do not commit VCF, GVCF, BAM, CRAM, FASTQ, or other genomic data. Refer to authorized public sample data by source and wrap it only with synthetic identities.
- Do not expose subject linkage to a caller who has only de-identified access. Assisted queries must use the governed query interface rather than raw table or file credentials.

## Reference builds and versions

- Require every pipeline run, ingestion, analysis, and generated query to declare the reference build and its immutable version or manifest digest explicitly.
- Fail on a missing, unavailable, or incompatible reference. Never infer a build from contig names, silently use a default, substitute another build, mix builds, or perform an implicit liftover.
- Keep the selected build in `reference_build` and retain the exact reference-data version or manifest digest in run provenance. Do not invent a `reference_version` variant column without first changing the schema contract.
- Publish corrected reference data as a new immutable version, retain referenced prior versions, and validate workflow/reference compatibility before compute is allocated.
- When comparing records across builds, separate or explicitly normalize them with a documented, versioned liftover process. Never compare coordinates as though builds were interchangeable.

## Positioning limits

- Describe this repository as a demo solution accelerator and reference architecture built from validated patterns.
- Do not describe it as a released Microsoft blueprint, Microsoft product, supported Microsoft offering, regulatory solution, or confirmed end-to-end customer deployment.
- Do not claim that the accelerator makes genomic data compliant. Compliance depends on customer configuration, jurisdiction, policies, and operating procedures.
- Do not add unverified customer attribution.
- Label AI-assisted analysis as exploratory. It is not a diagnosis, clinical determination, treatment recommendation, or clinical decision-support capability.
- Separate demonstrated behavior from specified-only behavior and production considerations.

## Responding to variant-store change requests

When asked to add a variant-store column, apply these rules without waiting for the contributor to restate them:

1. Name the current exact schema and the affected contract.
2. Reject PHI-bearing or real-identity fields for accelerator and demo data.
3. Explain whether the value is derivable; use null instead of fabricated values.
4. Require an OpenSpec schema update before implementing schema drift.
5. Identify reference-build/version and provenance implications.
6. Identify affected ingestion, rejected-record, query, visualization, documentation, and test surfaces.
7. Keep the response within the positioning limits above.
