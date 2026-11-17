#!/usr/bin/env bash
set -e
# Descarga los pesos de MuseTalk la primera vez (quedan en el volumen /opt/MuseTalk/models)
if [ ! -s /opt/MuseTalk/models/musetalkV15/unet.pth ] || [ ! -s /opt/MuseTalk/models/face-parse-bisent/79999_iter.pth ]; then
  echo "Primer arranque: descargando pesos de MuseTalk…"
  MUSETALK_DIR=/opt/MuseTalk SKIP_PIP=1 bash /tmp/install_musetalk.sh
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"
