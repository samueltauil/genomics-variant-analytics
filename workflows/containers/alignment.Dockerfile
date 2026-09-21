# Alignment stage container. Bundles samtools for BAM/CRAM formatting of the
# naive stub aligner's SAM output. This does not include a real short-read
# aligner (no BWA); see docs/secondary-pipeline.md for scope.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends samtools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/pipeline
COPY scripts/secondary_pipeline.py scripts/pipeline_provenance.py /opt/pipeline/scripts/
COPY workflows/bin/align_reads.py /usr/local/bin/align_reads.py
RUN chmod +x /usr/local/bin/align_reads.py \
    && touch /opt/pipeline/scripts/__init__.py

ENV PYTHONPATH=/opt/pipeline
# No ENTRYPOINT: see quality-control.Dockerfile for why Nextflow's generated
# shell wrapper must run directly rather than as an argument to an entrypoint.