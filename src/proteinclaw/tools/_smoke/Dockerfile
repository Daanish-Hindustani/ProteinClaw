# Smoke tool — proves the dispatch path. Kept tiny on purpose.
FROM nvidia/cuda:12.4.1-base-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY tool_entrypoint.py implementation.py /app/

# /workspace is bind-mounted by LocalRunner; mkdir is just a safety net for
# bare-`docker run` invocations.
RUN mkdir -p /workspace

ENTRYPOINT ["python3", "/app/tool_entrypoint.py"]
