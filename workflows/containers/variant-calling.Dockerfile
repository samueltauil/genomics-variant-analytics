# Variant-calling stage container. Naive per-position mismatch caller; not
# GATK. No claim of biological validation or GATK concordance.
FROM python:3.12-slim

WORKDIR /opt/pipeline
COPY scripts/secondary_pipeline.py scripts/pipeline_provenance.py /opt/pipeline/scripts/
COPY workflows/bin/call_variants.py /usr/local/bin/call_variants.py
RUN chmod +x /usr/local/bin/call_variants.py \
    && touch /opt/pipeline/scripts/__init__.py

ENV PYTHONPATH=/opt/pipeline
ENTRYPOINT ["call_variants.py"]