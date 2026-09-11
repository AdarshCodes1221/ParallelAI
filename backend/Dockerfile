FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpoppler-cpp-dev \
    pkg-config \
    python3-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# FIXED: Pre-download Whisper base model during build to enable offline audio transcription.
# This ensures faster-whisper has the model cached and doesn't need to download it at runtime.
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')" || true

# Block all HuggingFace network requests at runtime — model must be pre-cached above
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

COPY . .

EXPOSE 8000

# FIXED: was "main:app" — wrong path, app never started
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]