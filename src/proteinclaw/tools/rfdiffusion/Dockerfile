# RFdiffusion v1 (RosettaCommons/RFdiffusion).
#
# Mirrors the upstream docker/Dockerfile's pin set: CUDA 11.6 + Python 3.9 +
# torch 1.12.1+cu116 + dgl 1.0.2+cu116 + the bundled SE3Transformer fork.
# These pins are load-bearing — the SE3Transformer setup.py breaks with
# newer torch/dgl combos. Don't "modernise" without re-testing the build.
FROM nvcr.io/nvidia/cuda:11.6.2-cudnn8-runtime-ubuntu20.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DGLBACKEND=pytorch

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3.9 python3-pip git wget ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/RosettaCommons/RFdiffusion.git /app/RFdiffusion

# Pinned per upstream Dockerfile. dgl 1.0.2+cu116 wheels live on dgl.ai.
RUN python3.9 -m pip install --upgrade pip \
 && python3.9 -m pip install \
        "numpy<2" \
        dgl==1.0.2+cu116 -f https://data.dgl.ai/wheels/cu116/repo.html \
        torch==1.12.1+cu116 --extra-index-url https://download.pytorch.org/whl/cu116 \
 && python3.9 -m pip install \
        e3nn==0.3.3 \
        wandb==0.12.0 \
        pynvml==11.0.0 \
        decorator==5.1.0 \
        hydra-core==1.3.2 \
        pyrsistent==0.19.3 \
        git+https://github.com/NVIDIA/dllogger#egg=dllogger \
 && python3.9 -m pip install /app/RFdiffusion/env/SE3Transformer \
 && python3.9 -m pip install /app/RFdiffusion --no-deps

WORKDIR /app
COPY tool_entrypoint.py implementation.py _gpu_metrics.py _normalize.py /app/

RUN mkdir -p /workspace /cache/rfdiffusion \
 # RFdiffusion writes its noise schedule cache into a `schedules/` sibling
 # directory of the rfdiffusion package. As a UID-1000 process we can't
 # write to /usr/local/lib/... so pre-create the dir world-writable.
 && mkdir -p /usr/local/lib/python3.9/dist-packages/schedules \
 && chmod 777 /usr/local/lib/python3.9/dist-packages/schedules

ENTRYPOINT ["python3.9", "/app/tool_entrypoint.py"]
