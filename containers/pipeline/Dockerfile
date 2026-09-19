FROM python:3.12-slim

ARG ALIGNER_VERSION=synthetic-aligner-1.0.0
ARG VARIANT_CALLER_VERSION=synthetic-variant-caller-1.0.0
ARG UTILITY_VERSION=python-3.12

LABEL org.opencontainers.image.title="genomics-variant-pipeline" \
      org.opencontainers.image.description="Metadata-only accelerator pipeline image; replace synthetic toolchain values in a reviewed release" \
      org.genomics.tool.aligner="${ALIGNER_VERSION}" \
      org.genomics.tool.variant-caller="${VARIANT_CALLER_VERSION}" \
      org.genomics.tool.utility="${UTILITY_VERSION}"

WORKDIR /opt/pipeline
COPY containers/pipeline/toolchain.json /opt/pipeline/toolchain.json

ENTRYPOINT ["python", "-c", "import json; print(json.load(open('/opt/pipeline/toolchain.json')))" ]
