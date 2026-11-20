# Imagen CPU (motor Wav2Lip). Apta para el VPS (Dokploy) o cualquier PC sin GPU NVIDIA.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg fonts-dejavu-core git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "opencv-python-headless==4.10.0.84" \
 && pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir "librosa==0.10.2.post1" scipy soundfile tqdm

COPY install/install_wav2lip.sh /tmp/install_wav2lip.sh
RUN WAV2LIP_DIR=/opt/Wav2Lip SKIP_PIP=1 bash /tmp/install_wav2lip.sh

COPY app ./app
COPY static ./static

ENV ENGINE=wav2lip \
    WAV2LIP_DIR=/opt/Wav2Lip \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://localhost:8000/api/status || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
