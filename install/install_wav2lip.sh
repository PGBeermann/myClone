#!/usr/bin/env bash
# Instala el motor Wav2Lip (CPU / GPU / Apple Silicon) y descarga sus pesos.
#   Uso:  WAV2LIP_DIR=/opt/Wav2Lip bash install/install_wav2lip.sh
#   SKIP_PIP=1  → no instala paquetes de Python (útil dentro del Dockerfile)
set -euo pipefail
DIR="${WAV2LIP_DIR:-/opt/Wav2Lip}"
PY="${WAV2LIP_PYTHON:-python3}"

echo "==> Clonando Wav2Lip (Rudrabha/Wav2Lip) en $DIR"
if [ ! -d "$DIR/.git" ]; then
  git clone --depth 1 https://github.com/Rudrabha/Wav2Lip.git "$DIR"
fi

# Compatibilidad con PyTorch ≥ 2.6 en equipos sin CUDA: cargar el detector S3FD en CPU.
sed -i "s/torch.load(path_to_detector)/torch.load(path_to_detector, map_location='cpu')/" \
  "$DIR/face_detection/detection/sfd/sfd_detector.py"

if [ "${SKIP_PIP:-0}" != "1" ]; then
  echo "==> Instalando dependencias de Python"
  if command -v nvidia-smi >/dev/null 2>&1; then
    "$PY" -m pip install torch
  else
    "$PY" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
  fi
  "$PY" -m pip install "librosa>=0.10" scipy soundfile "opencv-python-headless>=4.8,<5" numpy
fi

download () {  # destino url1 url2 ...
  local dst="$1"; shift
  [ -s "$dst" ] && { echo "    ya existe: $dst"; return 0; }
  mkdir -p "$(dirname "$dst")"
  for url in "$@"; do
    echo "    descargando $url"
    if curl -fL --retry 3 -o "$dst.part" "$url"; then mv "$dst.part" "$dst"; return 0; fi
  done
  rm -f "$dst.part"; echo "ERROR: no se pudo descargar $(basename "$dst")"; return 1
}

echo "==> Descargando pesos"
download "$DIR/checkpoints/wav2lip_gan.pth" \
  "https://huggingface.co/camenduru/Wav2Lip/resolve/main/checkpoints/wav2lip_gan.pth" \
  "https://huggingface.co/NeuroDonu/Sadtalker-VideoLip/resolve/main/wav2lip_gan.pth"
download "$DIR/face_detection/detection/sfd/s3fd.pth" \
  "https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth" \
  "https://huggingface.co/camenduru/Wav2Lip/resolve/main/face_detection/detection/sfd/s3fd.pth"

# Verificación de integridad (SHA-256 publicado del checkpoint wav2lip_gan.pth, 436 MB)
EXPECTED="ca9ab7b7b812c0e80a6e70a5977c545a1e8a365a6c49d5e533023c034d7ac3d8"
GOT=$(sha256sum "$DIR/checkpoints/wav2lip_gan.pth" | cut -d' ' -f1)
if [ "$GOT" = "$EXPECTED" ]; then echo "    wav2lip_gan.pth: SHA-256 verificado"
else echo "    AVISO: SHA-256 distinto al esperado ($GOT). Verifique el origen del archivo."; fi

echo "==> Wav2Lip listo en $DIR"
echo "    Recuerde: los pesos de Wav2Lip son solo para uso personal, académico o de investigación."
