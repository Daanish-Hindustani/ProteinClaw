# ESMFold (facebook/esmfold_v1 via HuggingFace transformers).
# Same base + torch as ProteinMPNN — keeps the layer cache shared.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/cache/huggingface \
    HF_HUB_CACHE=/cache/huggingface \
    TRANSFORMERS_CACHE=/cache/huggingface

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3 python3-pip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip \
 && python3 -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124 \
 && python3 -m pip install \
        "transformers>=4.46,<5.0" \
        "accelerate>=0.34,<2.0" \
        "tokenizers>=0.20,<1.0" \
        numpy

# Pre-install the optional ESM module so first-run doesn't trip on a missing import.
# (transformers ESMFold uses its own ESM-2 weights; nothing else needed here.)

WORKDIR /app
COPY tool_entrypoint.py implementation.py _gpu_metrics.py _normalize.py /app/

RUN mkdir -p /workspace /cache/huggingface

ENTRYPOINT ["python3", "/app/tool_entrypoint.py"]
