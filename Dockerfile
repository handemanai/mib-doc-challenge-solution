FROM python:3.11-slim

# System libs for OpenCV (pulled in by RapidOCR) on a slim base.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*

# Offline runtime: all dependencies and OCR models are baked into the image.
# No LLM/VLM, no torch/paddle; nothing here follows instructions, so the
# injection surface the dataset targets does not exist in this system.
# opencv-python is pinned explicitly. It is a transitive dependency of
# rapidocr-onnxruntime, which only constrains opencv-python>=4.5.1.48 (no upper
# bound), so without this pin a clean rebuild floats to the newest release
# (e.g. OpenCV 5.x) and changes the image-preprocessing internals RapidOCR
# relies on -- making the score non-reproducible from a clean checkout.
# 4.11.0.86 is the validated version.
RUN pip install --no-cache-dir \
    pymupdf==1.28.0 \
    rapidocr-onnxruntime==1.4.4 \
    onnxruntime==1.20.1 \
    rapidfuzz==3.14.5 \
    numpy==2.2.6 \
    opencv-python==4.11.0.86

WORKDIR /app
COPY mib/ /app/mib/
COPY models/ /app/models/
COPY scripts/predict.py scripts/run_shard.py /app/scripts/
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

# Trigger RapidOCR model unpack at build time so runtime needs no writes
# outside /tmp, then verify the pipeline imports cleanly.
RUN python -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()" && \
    python -c "import sys; sys.path.insert(0, '/app'); import mib.pipeline"

ENV TMPDIR=/tmp
ENTRYPOINT ["/app/run.sh"]
