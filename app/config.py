"""Configuración central. Todo se controla con variables de entorno."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data")).resolve()

AVATARS_DIR = DATA_DIR / "avatars"   # videos de aprendizaje + metadatos
AUDIOS_DIR = DATA_DIR / "audios"     # audios normalizados a WAV 16 kHz mono
OUTPUTS_DIR = DATA_DIR / "outputs"   # videos generados
JOBS_DIR = DATA_DIR / "jobs"         # estado y bitácora de cada trabajo

for d in (AVATARS_DIR, AUDIOS_DIR, OUTPUTS_DIR, JOBS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Motor de síntesis:
#   "musetalk" → máxima calidad, requiere GPU NVIDIA (≥ 8 GB VRAM)
#   "wav2lip"  → funciona en CPU (o Apple Silicon); más lento y boca de menor resolución
#   "mock"     → solo pruebas de instalación/interfaz; no mueve los labios
ENGINE = os.getenv("ENGINE", "wav2lip").lower()
WAV2LIP_DIR = Path(os.getenv("WAV2LIP_DIR", "/opt/Wav2Lip")).resolve()
WAV2LIP_PYTHON = os.getenv("WAV2LIP_PYTHON", "python")
W2L_BATCH = int(os.getenv("W2L_BATCH", "32"))
MUSETALK_DIR = Path(os.getenv("MUSETALK_DIR", "/opt/MuseTalk")).resolve()
MUSETALK_PYTHON = os.getenv("MUSETALK_PYTHON", "python")
MUSETALK_VERSION = os.getenv("MUSETALK_VERSION", "v15")
GPU_ID = int(os.getenv("GPU_ID", "0"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "20"))

FPS = 25                       # MuseTalk trabaja a 25 fps
MAX_ENROLL_SECONDS = int(os.getenv("MAX_ENROLL_SECONDS", "90"))
MIN_ENROLL_SECONDS = int(os.getenv("MIN_ENROLL_SECONDS", "10"))
MAX_AUDIO_SECONDS = int(os.getenv("MAX_AUDIO_SECONDS", "900"))
ENROLL_MAX_HEIGHT = int(os.getenv("ENROLL_MAX_HEIGHT", "720"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))

# Si se define, todas las rutas /api exigen "Authorization: Bearer <APP_TOKEN>"
APP_TOKEN = os.getenv("APP_TOKEN", "").strip()

# Marca de agua de transparencia ("Contenido generado con IA")
WATERMARK_TEXT = os.getenv("WATERMARK_TEXT", "Contenido generado con IA")
FONT_FILE = os.getenv("FONT_FILE", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
