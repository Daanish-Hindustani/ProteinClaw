# ESMFold structure prediction from sequence.
#
# This follows the ProteinClaw/celltype-agent pattern: use the HuggingFace
# ESMFold implementation directly instead of the brittle upstream `esm-fold`
# shell entrypoint and its old OpenFold build.

FROM nvcr.io/nvidia/pytorch:25.04-py3

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir \
    transformers \
    accelerate \
    biopython \
    numpy \
    sentencepiece

COPY esmfold/tool_entrypoint.py /opt/tool_entrypoint.py
COPY esmfold/implementation.py /opt/implementation.py

RUN python3 - <<'PY'
from transformers import AutoTokenizer, EsmForProteinFolding

tokenizer = AutoTokenizer.from_pretrained("facebook/esmfold_v1")
model = EsmForProteinFolding.from_pretrained("facebook/esmfold_v1")
assert tokenizer is not None
assert model is not None
PY

RUN mkdir -p /work
WORKDIR /work

ENTRYPOINT ["python3", "/opt/tool_entrypoint.py"]
