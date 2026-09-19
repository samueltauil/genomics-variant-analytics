/*
 * Portable Nextflow definition for the local/containerized secondary-analysis
 * pipeline: quality control -> alignment -> variant calling, over a tiny,
 * runtime-generated synthetic demo sample (never a real or committed
 * sequencing file).
 *
 * This pipeline covers OpenSpec tasks 5.1 (author the pipeline), 5.5 (run
 * provenance), and 5.6 (stage-level failure handling) for the local scope.
 * Azure Batch and Slurm profiles (conf/azure_batch.config, conf/slurm.config)
 * are configuration preparation only in this scope: they declare the
 * executor and a managed-identity/credential-free process configuration
 * without provisioning or requiring a live pool, cluster, or Managed Lustre
 * file system. Container definitions are provided under containers/ but the
 * default profile runs bin/ scripts directly with the local executor so this
 * pipeline is runnable without a container daemon.
 *
 * The alignment/variant-calling stages here are intentionally naive stand-
 * ins: there is no real short-read aligner and no GATK-equivalent caller.
 * They do not claim biological validation, alignment accuracy, or GATK
 * concordance -- see docs/secondary-pipeline.md for the exact scope.
 */

nextflow.enable.dsl = 2

params.run_id             = null
params.reference_build    = null
params.reference_version  = null
params.sample_id          = 'SYN-SAMPLE-0001'
params.read_count         = 12
params.aligned_format      = 'bam'   // 'bam' or 'cram'
params.variant_format      = 'vcf'   // 'vcf' or 'gvcf'
params.force_fail_stage    = null    // 'quality_control' | 'alignment' | 'variant_calling'
params.outdir              = 'results'
params.workflow_id         = 'genomics-secondary-analysis'
params.workflow_version    = 'v0.1.0'
params.execution_target    = 'local'
params.compute_pool        = 'local-dev'
params.provenance_db       = 'provenance.sqlite3'

process GENERATE_DEMO_SAMPLE {
    // Preparatory synthetic-input synthesis; not one of the three pipeline
    // stages. Fails closed if the declared reference build/version does not
    // match the generated reference's own content-derived identity.
    publishDir "${params.outdir}/inputs", mode: 'copy'

    output:
    tuple path('sample_manifest.json'), path('*.fastq'), path('reference.fasta'), emit: bundle

    script:
    """
    generate_demo_sample.py \
        --reference-build ${params.reference_build} \
        --reference-version ${params.reference_version} \
        --sample-id ${params.sample_id} \
        --read-count ${params.read_count}
    """
}

process QUALITY_CONTROL {
    input:
    tuple path(manifest), path(fastqs), path(reference)

    output:
    path 'qc_report.json', emit: report
    tuple path(manifest), path(fastqs), path(reference), emit: bundle

    script:
    def failFlag = params.force_fail_stage == 'quality_control' ? '--force-fail' : ''
    """
    quality_control.py --manifest ${manifest} ${failFlag}
    """
}

process ALIGN_READS {
    input:
    tuple path(manifest), path(fastqs), path(reference)

    output:
    path "*.${params.aligned_format == 'cram' ? 'cram' : 'bam'}*", emit: aligned
    tuple path(manifest), path(fastqs), path(reference), emit: bundle

    script:
    def failFlag = params.force_fail_stage == 'alignment' ? '--force-fail' : ''
    """
    align_reads.py --manifest ${manifest} --output-format ${params.aligned_format} ${failFlag}
    """
}

process CALL_VARIANTS {
    input:
    tuple path(manifest), path(fastqs), path(reference)

    output:
    path "*.${params.variant_format == 'gvcf' ? 'g.vcf' : 'vcf'}", emit: variants

    script:
    def failFlag = params.force_fail_stage == 'variant_calling' ? '--force-fail' : ''
    """
    call_variants.py --manifest ${manifest} --output-format ${params.variant_format} ${failFlag}
    """
}

process PUBLISH_RESULTS {
    // Only scheduled once quality control, alignment, and variant calling
    // have all completed successfully, because it consumes their outputs as
    // inputs. A stage failure upstream stops the pipeline before this
    // process is ever invoked, so a failed run never publishes partial
    // outputs as a complete result.
    publishDir params.outdir, mode: 'copy'

    input:
    path qc_report
    path aligned
    path variants

    output:
    path qc_report
    path aligned
    path variants

    script:
    """
    true
    """
}

workflow {
    if( !params.run_id )
        exit 1, "run_id is required; there is no default run identifier."
    if( !params.reference_build )
        exit 1, "reference_build is required; no reference build may be inferred or defaulted."
    if( !params.reference_version )
        exit 1, "reference_version is required; no fallback reference version is permitted."

    def VALID_STAGES = ['quality_control', 'alignment', 'variant_calling']
    if( params.force_fail_stage && !(params.force_fail_stage in VALID_STAGES) )
        exit 1, "force_fail_stage must be one of ${VALID_STAGES} or unset."

    sample = GENERATE_DEMO_SAMPLE()
    qc = QUALITY_CONTROL(sample.bundle)
    aligned = ALIGN_READS(qc.bundle)
    variants = CALL_VARIANTS(aligned.bundle)
    PUBLISH_RESULTS(qc.report, aligned.aligned, variants.variants)
}

// Run provenance for this workflow's execution is persisted by the external
// launcher (scripts/run_nextflow_secondary_pipeline.py), which wraps
// `nextflow run` as a subprocess, inspects its exit code and `.nextflow.log`
// to identify a failing stage, and calls the same
// scripts/pipeline_provenance.record_run used by the pure-Python
// orchestrator. Nextflow's own DSL2 `workflow.onComplete` handler is not
// used for this because, in this Nextflow version, referencing `params`/
// `workflow` from a closure nested inside the `workflow {}` body resolves to
// null rather than the running workflow's bindings.
