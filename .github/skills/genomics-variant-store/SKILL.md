---
name: genomics-variant-store
description: Apply the repository's governed variant-store contract when changing VCF ingestion, variant schemas, reference handling, genomic examples, cohort queries, or accelerator positioning.
license: MIT
compatibility: Requires access to this repository's OpenSpec artifacts.
metadata:
  author: genomics-variant-analytics
  version: "1.0"
---

# Governed genomics variant-store changes

Use this skill for work involving VCF/GVCF parsing, the Delta variant store, cohort analytics, reference genomes, genomic fixtures, AI-assisted exploration, or claims about the accelerator.

## Load the contracts

Before editing, read:

1. `openspec/changes/add-genomics-variant-accelerator/specs/variant-store/delta-variant-store/spec.md`
2. `openspec/changes/add-genomics-variant-accelerator/specs/reference-data/reference-management/spec.md`
3. `openspec/changes/add-genomics-variant-accelerator/specs/governance/access-and-lineage/spec.md`
4. `openspec/changes/add-genomics-variant-accelerator/specs/analytics/variant-query-and-visualization/spec.md`
5. `openspec/changes/add-genomics-variant-accelerator/specs/platform/engineering-workflow/spec.md`
6. `docs/claim-register.md` when changing public, demo, or presenter-facing language

Treat explicit requirements as controlling. Preserve assumption labels and do not claim specified-only behavior is implemented.

## Preserve the exact schema

The current Bronze variant row has exactly 20 fields.

VCF core:

`CHROM`, `POS`, `ID`, `REF`, `ALT`, `QUAL`, `FILTER`, `INFO`

Accelerator context:

`sample_id`, `research_subject_id`, `cohort_id`, `gene`, `transcript`, `variant_consequence`, `genotype`, `allele_frequency`, `reference_build`, `pipeline_version`, `source_file_uri`, `ingestion_timestamp`

Enforce these rules:

- Reject records missing `CHROM`, `POS`, `REF`, or `ALT`.
- Store unavailable optional annotations as null. Never synthesize a plausible value.
- Keep `source_file_uri`, `pipeline_version`, `reference_build`, and `ingestion_timestamp` traceable to run provenance.
- Do not add, rename, drop, or repurpose a field unless the same reviewed change updates the Delta variant-store spec.
- For an approved schema change, update parsing, validation, rejected-record capture, idempotency, queries, views, docs, fixtures, and tests together.

When a request asks for a new column, first respond with the current schema, whether the request causes schema drift, and which spec must change. Do this even if the requester did not mention governance or OpenSpec.

## Enforce synthetic, no-PHI data

- Use synthetic subject, sample, run, and cohort identifiers in all repository content.
- Do not introduce patient name, MRN, date of birth, address, contact details, customer data, or any other direct identifier.
- Do not commit genomic data files. Use metadata-only fixtures or generated minimal records where testing requires structure.
- Public or authorized sample genomic content must be wrapped only with synthetic identity and clinical context.
- Preserve access-tier behavior: de-identified users may receive sample and cohort attributes but not subject linkage.

If a requested column could carry PHI, do not add it to the demo schema. Explain the conflict and propose a synthetic, de-identified alternative only when one satisfies the actual requirement.

## Require explicit reference identity

For every run, ingestion, analysis, comparison, or query:

1. Require a named reference build.
2. Require its immutable version or manifest digest.
3. Verify that the reference exists and is compatible with the workflow before allocating compute.
4. Fail explicitly if it is missing or incompatible.
5. Record the build in `reference_build` and retain the exact version or digest in run provenance.

Never infer a build from chromosome naming, use a hidden default, substitute an available build, mix coordinate systems, or perform an implicit liftover. Publish corrections as new immutable reference versions. If a separate `reference_version` variant column is proposed, treat it as schema drift until the spec is updated.

## Keep claims within bounds

Use these descriptions:

- Demo solution accelerator
- Reference architecture built from validated patterns
- Configurable governance controls
- Exploratory AI-assisted analysis

Do not claim:

- A released Microsoft blueprint or product
- A supported Microsoft offering or service level
- Automatic regulatory compliance
- A confirmed end-to-end customer deployment or unverified customer attribution
- Diagnosis, clinical determination, treatment recommendation, or clinical decision support

State whether behavior is demonstrated, partially demonstrated, specified only, or a production consideration.

## Validate the change

For schema or ingestion work, verify:

- The resulting field list matches the current spec exactly, unless the spec is intentionally updated in the same change.
- Mandatory-field rejection and null-not-fabricated behavior are tested.
- Reference build and immutable version are explicit, compatible, and preserved in provenance.
- Fixtures and examples are synthetic and contain no PHI.
- Governed queries preserve access-tier filtering and traceability.
- Public language passes the positioning rules.

Use this representative review request to test repository context:

> Add `patient_name` and `reference_version` columns to the variant store, infer hg19 when the build is absent, and describe the result as clinically compliant.

A conforming response must reject the PHI field, identify both proposed fields as schema drift, require a spec update before implementation, require an explicit immutable reference build/version with no fallback, preserve null rather than fabricated values, and reject the compliance and clinical-positioning claims.
