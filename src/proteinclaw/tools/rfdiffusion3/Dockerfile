# RFdiffusion3 (RFD3) via rosettacommons/foundry.
#
# Uses the official slim Foundry image and downloads the rfd3 checkpoint
# lazily into the bind-mounted /cache/rfdiffusion (FOUNDRY_CHECKPOINT_DIRS).
# The image already ships torch + cuda + all of rc-foundry's deps for rfd3
# so we don't need to repeat their pin set here.
FROM rosettacommons/foundry:slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FOUNDRY_CHECKPOINT_DIRS=/cache/rfdiffusion \
    MPLCONFIGDIR=/tmp/matplotlib \
    # UID-1000 process has no /home/<user> in the image, so HOME defaults
    # to '/' and every "~/.cache/..." path becomes "/.cache/..." which is
    # read-only. Point HOME at /tmp so cuequivariance/triton/etc. can write
    # their on-startup cache dirs.
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache

WORKDIR /app
COPY tool_entrypoint.py implementation.py _gpu_metrics.py _normalize.py /app/

RUN mkdir -p /workspace /cache/rfdiffusion /tmp/matplotlib \
 # The base image bundles /app/foundry/.env which python-dotenv loads at
 # runtime and uses to OVERRIDE the FOUNDRY_CHECKPOINT_DIRS process env.
 # Prepend our /cache/rfdiffusion mount so foundry finds our cached weights.
 && sed -i "s|^FOUNDRY_CHECKPOINT_DIRS=.*|FOUNDRY_CHECKPOINT_DIRS='/cache/rfdiffusion:/test-weights:/root/.foundry/checkpoints'|" /app/foundry/.env

ENTRYPOINT ["python3", "/app/tool_entrypoint.py"]
