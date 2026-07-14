FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BOLTZ_CACHE=/cache/boltz2

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential ca-certificates python3 python3-dev python3-pip \
 && rm -rf /var/lib/apt/lists/*

# Pin the public model/tool contract. Update the tool docs and calibration
# fixtures before changing this version.
RUN python3 -m pip install --break-system-packages "boltz[cuda]==2.2.1"

WORKDIR /app
COPY implementation.py tool_entrypoint.py /app/
RUN mkdir -p /workspace /cache/boltz2

ENTRYPOINT ["python3", "/app/tool_entrypoint.py"]
