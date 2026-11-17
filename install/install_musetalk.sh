#!/usr/bin/env bash
# Instala MuseTalk 1.5 (requiere GPU NVIDIA + CUDA 11.8) y descarga sus pesos.
#   Uso:  MUSETALK_DIR=/opt/MuseTalk bash install/install_musetalk.sh
#   Se recomienda un entorno con Python 3.10 (p. ej.: conda create -n musetalk python=3.10).
#   SKIP_PIP=1   → solo clona y descarga pesos
set -euo pipefail
DIR="${MUSETALK_DIR:-/opt/MuseTalk}"
PY="${MUSETALK_PYTHON:-python3}"

echo "==> Clonando MuseTalk (TMElyralab/MuseTalk) en $DIR"
[ -d "$DIR/.git" ] || git clone --depth 1 https://github.com/TMElyralab/MuseTalk.git "$DIR"

if [ "${SKIP_PIP:-0}" != "1" ]; then
  echo "==> PyTorch 2.0.1 + CUDA 11.8 (versión validada por los autores)"
  "$PY" -m pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118
  "$PY" -m pip install -r "$DIR/requirements.txt"
  echo "==> Paquetes OpenMMLab (detección de landmarks DWPose)"
  "$PY" -m pip install --no-cache-dir -U openmim
  "$PY" -m mim install mmengine
  "$PY" -m mim install "mmcv==2.0.1"
  "$PY" -m mim install "mmdet==3.1.0"
  "$PY" -m mim install "mmpose==1.1.0"
fi

echo "==> Descargando pesos (≈ 3 GB)"
"$PY" -m pip install -q -U "huggingface_hub[cli]" gdown
cd "$DIR"
M=models
mkdir -p $M/musetalk $M/musetalkV15 $M/syncnet $M/dwpose $M/face-parse-bisent $M/sd-vae $M/whisper
export HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"
"$PY" - <<'EOF'
from huggingface_hub import snapshot_download as get
M = "models"
get("TMElyralab/MuseTalk", local_dir=M, allow_patterns=["musetalkV15/musetalk.json", "musetalkV15/unet.pth",
                                                        "musetalk/musetalk.json", "musetalk/pytorch_model.bin"])
get("stabilityai/sd-vae-ft-mse", local_dir=f"{M}/sd-vae", allow_patterns=["config.json", "diffusion_pytorch_model.bin"])
get("openai/whisper-tiny", local_dir=f"{M}/whisper",
    allow_patterns=["config.json", "pytorch_model.bin", "preprocessor_config.json"])
get("yzd-v/DWPose", local_dir=f"{M}/dwpose", allow_patterns=["dw-ll_ucoco_384.pth"])
get("ByteDance/LatentSync", local_dir=f"{M}/syncnet", allow_patterns=["latentsync_syncnet.pt"])
EOF
[ -s $M/face-parse-bisent/79999_iter.pth ] || gdown --id 154JgKpzCPW82qINcVieuPH3fZ2e0P812 -O $M/face-parse-bisent/79999_iter.pth
[ -s $M/face-parse-bisent/resnet18-5c106cde.pth ] || curl -fL https://download.pytorch.org/models/resnet18-5c106cde.pth -o $M/face-parse-bisent/resnet18-5c106cde.pth

echo "==> MuseTalk listo en $DIR"
