# AlphaFold2-multimer via ColabFold (sokrypton/ColabFold).
# JAX CUDA build is the load-bearing dep; pin it tightly.
# CUDA 12.2 + cuDNN 8 — jax 0.4.23 was built against this combination.
# Newer images (CUDA 12.4+) only ship cuDNN 9, which jax 0.4.23 + pinned
# `nvidia-cudnn-cu12` reject at runtime with CUDNN_STATUS_INTERNAL_ERROR.
FROM nvcr.io/nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    XLA_PYTHON_CLIENT_PREALLOCATE=false \
    TF_FORCE_UNIFIED_MEMORY=1 \
    COLABFOLD_DATA=/cache/openfold \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3 python3-pip git ca-certificates wget \
 && rm -rf /var/lib/apt/lists/*

# Pin numpy<2 first so every downstream wheel (pandas, jax, colabfold deps)
# binds against the numpy 1.x ABI. Without this, jax force-reinstall pulls
# numpy 2.x and pandas breaks at runtime with a numpy.dtype ABI error.
#
# jax 0.4.23 is the last version where ColabFold 1.5.5 + dm-haiku both
# import cleanly. Newer jax versions removed jax.linear_util at the top
# level, which both colabfold.batch.run and haiku._src.dot import directly.
# If you bump ColabFold past 1.5.5, re-evaluate the jax pin.
RUN python3 -m pip install --upgrade pip \
 && python3 -m pip install "numpy<2" \
 && python3 -m pip install \
        "colabfold[alphafold]==1.5.5" \
 && python3 -m pip install --force-reinstall \
        "jax[cuda12]==0.4.23" \
        "numpy<2" \
        -f https://storage.googleapis.com/jax-releases/jax_cuda_releases.html

WORKDIR /app
COPY tool_entrypoint.py implementation.py _gpu_metrics.py _normalize.py /app/

# ipSAE interface scorer (Dunbrack Lab, MIT). Pinned to a commit SHA for
# reproducibility — the script reads ColabFold's *_scores_rank_001_*.json PAE
# matrix + the rank-1 PDB and emits ipSAE / ipTM / pDockQ / LIS. numpy-only,
# already satisfied by the colabfold install above.
ARG IPSAE_SHA=6174cf9e71cb1bd660cc805856a18c4871a6dec3
RUN wget -q "https://raw.githubusercontent.com/DunbrackLab/IPSAE/${IPSAE_SHA}/ipsae.py" \
        -O /app/ipsae.py

# Pre-create the OpenFold params cache. ColabFold writes downloaded params
# under this dir on first call (~5 GB).
RUN mkdir -p /workspace /cache/openfold

ENTRYPOINT ["python3", "/app/tool_entrypoint.py"]
