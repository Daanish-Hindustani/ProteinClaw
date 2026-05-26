# RFantibody — Baker Lab antibody-finetuned RFdiffusion pipeline.
#
# Base: CUDA 11.8 + cuDNN 8 on Ubuntu 22.04 (RFantibody requirement).
# Model weights are NOT baked in — they are downloaded on first call
# by implementation.py and cached in the bind-mounted /cache/rfantibody.
#
# Build args:
#   RFANTIBODY_COMMIT  git ref to pin (default: main; pin to a SHA for prod)
FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ARG RFANTIBODY_COMMIT=main

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    MPLCONFIGDIR=/tmp/matplotlib \
    RFANTIBODY_HOME=/app/rfantibody \
    RFANTIBODY_WEIGHTS=/cache/rfantibody

RUN apt-get update && apt-get install --no-install-recommends -y \
        python3.10 python3.10-dev python3-pip \
        git wget curl build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (same version-pin approach as every other ProteinClaw tool)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Clone RFantibody and install its Python deps into an in-tree venv.
# --depth 1 keeps the image small; pin RFANTIBODY_COMMIT for reproducibility.
RUN git clone --depth 1 https://github.com/RosettaCommons/RFantibody.git \
        /app/rfantibody \
    && cd /app/rfantibody \
    && git fetch --depth 1 origin ${RFANTIBODY_COMMIT} \
    && git checkout ${RFANTIBODY_COMMIT}

WORKDIR /app/rfantibody
RUN uv sync

# Add the rfantibody venv's bin/ to PATH so rfdiffusion / proteinmpnn /
# rf2 / qvextract / qvscorefile are callable by name at runtime.
ENV PATH="/app/rfantibody/.venv/bin:$PATH"

# Create mount-point stubs; actual weights land in the bind-mounted
# /cache/rfantibody at runtime (lazy download on first call).
RUN mkdir -p /workspace /cache/rfantibody /tmp/matplotlib /tmp/.cache

# Copy ProteinClaw tool shims.  _gpu_metrics.py is injected by LocalRunner
# via the shared-build-files staging path (same as every GPU tool).
COPY tool_entrypoint.py implementation.py _gpu_metrics.py _normalize.py /app/

WORKDIR /app
ENTRYPOINT ["python3", "/app/tool_entrypoint.py"]
