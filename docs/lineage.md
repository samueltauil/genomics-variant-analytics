# End-to-end lineage (local reference implementation)

The accelerator's record-level lineage is resolved by joining four local
surfaces:

1. `VariantStore` provenance maps each exact 20-field variant row to its
   source VCF URI, pipeline run, pipeline version, reference build, and
   immutable reference manifest digest.
2. `MetadataStore` traverses the synthetic
   Subject -> Sample -> Sequencing Run -> FASTQ -> BAM/CRAM -> VCF chain.
3. `StagingLog` maps the VCF URI to its verified landing-zone source and keeps
   the source/destination relationship valid after a storage-tier change.
4. `CatalogContext` supplies item-level catalog labels. It is explicitly a
   **Microsoft Purview catalog-context simulation** (`mode: simulation`,
   `live: false`), not a live Purview integration. Purview item context does
   not replace record-level provenance.

`LineageResolver.backward_trace` accepts an analytics result and returns the
variant, producing run, VCF artifact, staged artifact, landing file, metadata
chain, and catalog context. `forward_trace` accepts a landing-zone path and
returns the verified staged artifact and all derived pipeline/variant records.

Both directions require governed variant-store access. Subject identifiers and
subject entities are returned only when the caller has the `subject_linkage`
capability. Raw content readability is reported separately and requires the
`raw_genomic_files` tier; a caller can receive lineage metadata without being
allowed to read FASTQ, BAM/CRAM, or VCF bytes. Fixtures use synthetic
identifiers and runtime-generated VCF text only; no genomic payload is stored
in the repository.
