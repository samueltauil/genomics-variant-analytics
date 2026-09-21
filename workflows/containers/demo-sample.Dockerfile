# Synthetic-input generation stage container. Produces the tiny runtime demo
# FASTA/FASTQ bundle; never bundles or fetches real sequencing data.
FROM python:3.12-slim

WORKDIR /opt/pipeline
COPY scripts/secondary_pipeline.py scripts/pipeline_provenance.py /opt/pipeline/scripts/
COPY workflows/bin/generate_demo_sample.py /usr/local/bin/generate_demo_sample.py
RUN chmod +x /usr/local/bin/generate_demo_sample.py \
    && touch /opt/pipeline/scripts/__init__.py

ENV PYTHONPATH=/opt/pipeline
# No ENTRYPOINT: see quality-control.Dockerfile for why Nextflow's generated
# shell wrapper must run directly rather than as an argument to an entrypoint.
