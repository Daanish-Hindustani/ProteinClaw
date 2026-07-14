FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OPENMM_PLUGIN_DIR=/usr/local/lib/python3.12/dist-packages/OpenMM.libs/lib/plugins

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git python3 python3-pip \
 && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --break-system-packages \
      "openmm==8.5.2" \
      "openmm-cuda-12==8.5.2" \
      "biopython==1.87" \
      "git+https://github.com/openmm/pdbfixer.git@5e658a4fb8d2b90d65ca8408c845cbf104ce7099"

WORKDIR /app
COPY implementation.py tool_entrypoint.py /app/
RUN mkdir -p /workspace

ENTRYPOINT ["python3", "/app/tool_entrypoint.py"]
