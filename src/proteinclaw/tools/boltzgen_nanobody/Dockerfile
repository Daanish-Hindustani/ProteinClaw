FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/cache/boltzgen \
    TORCH_HOME=/cache/boltzgen/torch

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential ca-certificates git python3 python3-dev python3-pip \
 && rm -rf /var/lib/apt/lists/*

# Keep the code, scaffold definitions, and weights interface tied to one release.
RUN git clone --depth 1 --branch v0.3.2 https://github.com/HannesStark/boltzgen.git /opt/boltzgen \
 && python3 -m pip install --break-system-packages /opt/boltzgen

WORKDIR /app
COPY implementation.py tool_entrypoint.py /app/
RUN mkdir -p /workspace /cache/boltzgen

ENTRYPOINT ["python3", "/app/tool_entrypoint.py"]
