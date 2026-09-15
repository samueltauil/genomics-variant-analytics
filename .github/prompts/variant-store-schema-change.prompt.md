---
description: "Review or implement a governed change to the exact variant-store schema"
---

Evaluate this requested variant-store change:

`${input:request:Describe the column or schema change}`

Use the repository instructions and the current OpenSpec files as the source of truth. Read the Delta variant-store, reference-management, governance, analytics, and engineering-workflow specs before proposing edits.

The current exact Bronze schema is:

- VCF core: `CHROM`, `POS`, `ID`, `REF`, `ALT`, `QUAL`, `FILTER`, `INFO`
- Accelerator context: `sample_id`, `research_subject_id`, `cohort_id`, `gene`, `transcript`, `variant_consequence`, `genotype`, `allele_frequency`, `reference_build`, `pipeline_version`, `source_file_uri`, `ingestion_timestamp`

In the response:

1. Repeat the current exact schema and identify which fields the request would affect.
2. Classify the request as no schema change, a compatible change outside the variant row, or schema drift requiring a reviewed OpenSpec update.
3. Reject any field or example that carries real identity or PHI. Use clearly synthetic identifiers and attributes only.
4. State whether the value is derivable. Preserve null when an optional value cannot be derived; do not fabricate it.
5. Require an explicit reference build and immutable reference version or manifest digest. Do not infer, default, substitute, mix, or silently liftover builds.
6. Explain the impact on ingestion, rejected records, provenance, governed queries, visualizations, documentation, and tests.
7. Preserve the accelerator positioning: exploratory, not clinical decision support; no compliance, released-blueprint, supported-offering, customer-deployment, or customer-attribution claim.

Do not implement a new variant column until the schema contract is updated in the same change. If implementation is requested and the contract already permits it, make the smallest complete change and validate every affected surface.
