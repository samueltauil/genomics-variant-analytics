# Quality-control stage container. Pure Python; no bioinformatics tool
# dependency for this stage.
FROM python:3.12-slim

WORKDIR /opt/pipeline
COPY scripts/secondary_pipeline.py scripts/pipeline_provenance.py /opt/pipeline/scripts/
COPY workflows/bin/quality_control.py /usr/local/bin/quality_control.py
RUN chmod +x /usr/local/bin/quality_control.py \
    && touch /opt/pipeline/scripts/__init__.py

ENV PYTHONPATH=/opt/pipeline
# No ENTRYPOINT: Nextflow invokes the staged script on PATH via its own
# generated shell wrapper (.command.run) inside the container. Setting an
# ENTRYPOINT here would swallow that wrapper invocation as an argument to the
# entrypoint binary instead of letting the container shell run it directly.