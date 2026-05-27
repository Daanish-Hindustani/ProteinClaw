# ProteinMPNN — inverse-folding sequence design.
# Base image: CUDA 12.4 runtime with cuDNN (torch wheels work fine).
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Python + git for the upstream clone. No PPA needed — Ubuntu 22.04 ships
# Python 3.10 by default which torch supports.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3 python3-pip git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# torch built for CUDA 12.1 wheels works fine on the CUDA 12.4 runtime
# (NVIDIA forward-compat). Avoids waiting for cu124 wheels to stabilise.
RUN python3 -m pip install --upgrade pip \
 && python3 -m pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cu121 \
 && python3 -m pip install numpy

# ProteinMPNN repo + bundled vanilla weights (~50 MB). Pinning to a commit
# would be safer; for v1 we pull the head and rely on the API stability.
RUN git clone --depth 1 https://github.com/dauparas/ProteinMPNN.git /opt/ProteinMPNN

ENV PYTHONPATH=/opt/ProteinMPNN

WORKDIR /app
COPY tool_entrypoint.py implementation.py _gpu_metrics.py _normalize.py /app/

# Bind-mounted by LocalRunner; mkdir is a safety net for `docker run` outside
# the LocalRunner path.
RUN mkdir -p /workspace

ENTRYPOINT ["python3", "/app/tool_entrypoint.py"]
