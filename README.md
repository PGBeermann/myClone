# Clon Docente

Software libre para generar **videos de su propia persona** con **sincronización labial** a partir de cualquier audio, por ejemplo una clase grabada, una narración o una voz sintetizada.

El flujo tiene tres pasos:

1. **Sesión de aprendizaje facial.** Usted graba un video guiado de unos 30 s con la cámara web, o sube uno. El sistema verifica la calidad del material y luego "aprende" su rostro. Detecta el rostro y sus landmarks cuadro a cuadro, construye la región facial suavizada en el tiempo y, con MuseTalk, también los latentes y las máscaras de fusión de cada cuadro. Esto se hace **una sola vez** por avatar.
2. **Entrada de audio.** Puede grabar con el micrófono o subir un archivo WAV, MP3, M4A u OGG, o un video con audio. El audio se normaliza a 16 kHz mono con loudnorm EBU R128.
3. **Generación.** La boca se regenera cuadro a cuadro según el audio, se fusiona con una máscara suavizada y se exporta en MP4 (H.264 + AAC). Por transparencia, el video lleva de forma opcional la marca de agua *"Contenido generado con IA"*.

---

## Por qué esta plataforma

| Componente | Elección | Motivo |
|---|---|---|
| Lenguaje del motor | **Python** | Todos los modelos de sincronización labial de código abierto están en PyTorch. Node.js solo podría orquestarlos desde fuera. |
| Servidor | **FastAPI + Uvicorn** | Es asíncrono, maneja bien la subida de archivos grandes y se documenta solo (`/docs`). |
| Interfaz | **HTML/CSS/JavaScript** sin frameworks | Usa `getUserMedia` y `MediaRecorder` del navegador para la cámara y el micrófono. Funciona en PC y en celular. |
| Despliegue | **Docker** (CPU y GPU) | Es el mismo esquema que Dokploy en su VPS. |
| Cola de trabajos | Un solo proceso trabajador | La GPU o la CPU procesa un trabajo a la vez. Así se evitan errores por falta de memoria. |

### Motores (todos gratuitos)

| Motor | Hardware | Calidad | Velocidad aproximada | Licencia de los pesos |
|---|---|---|---|---|
| **MuseTalk 1.5** (`ENGINE=musetalk`) | GPU NVIDIA ≥ 8 GB VRAM | Alta (región facial de 256×256) | Tiempo real o más rápido | MIT (uso comercial permitido) |
| **Wav2Lip GAN** (`ENGINE=wav2lip`) | **CPU**, Apple Silicon o GPU | Media (boca de 96×96, reescalada y fusionada) | CPU de 2 núcleos: ~10 cuadros/s, unas 2,5 veces más lento que tiempo real | Solo uso personal, académico o de investigación |
| Prueba (`ENGINE=mock`) | Cualquiera | No mueve los labios | Inmediato | — |

Un avatar aprendido con un motor debe volver a aprender si se cambia de motor. La interfaz lo indica.

---

## Opción A · Su VPS con Dokploy (CPU, sin GPU)

1. Suba esta carpeta a un repositorio de GitHub, por ejemplo `PGBeermann/myClone`.
2. En Dokploy, cree una aplicación desde el repositorio con tipo de compilación **Dockerfile** (el `Dockerfile` de la raíz).
3. Defina las variables de entorno:
   ```
   APP_TOKEN=<una clave larga>      # obligatoria: protege el acceso
   W2L_BATCH=32
   ```
4. Cree un volumen persistente montado en **`/data`**.
5. Asigne un dominio con HTTPS, por ejemplo `clon.vipcursos.cloud`, puerto **8000**.
   **El HTTPS es imprescindible**, porque los navegadores solo permiten usar la cámara y el micrófono en sitios seguros.

La imagen descarga los pesos de Wav2Lip (~0,5 GB) durante la compilación.

## Opción B · PC con GPU NVIDIA (MuseTalk, máxima calidad)

Requisitos: controlador NVIDIA reciente, Docker y **NVIDIA Container Toolkit** (en Windows, use Docker Desktop con WSL2).

```bash
APP_TOKEN=miclave docker compose --profile gpu up -d --build clon-gpu
# Abra http://localhost:8001  (el primer arranque descarga ~3 GB de pesos)
```

## Opción C · GPU gratuita en Kaggle (si no tiene NVIDIA)

Abra `kaggle/clon_docente_kaggle.ipynb` en Kaggle y active **GPU** e **Internet**. Ajuste `REPO_URL` y `APP_TOKEN` y pulse *Run All*. Al final obtendrá un enlace HTTPS temporal (Cloudflare Quick Tunnel) para usar la aplicación desde cualquier navegador. Descargue sus videos antes de cerrar la sesión.

## Opción D · Ejecución local sin Docker (Linux, macOS o Windows con WSL)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt "opencv-python-headless==4.10.0.84"
WAV2LIP_DIR=$PWD/engines/Wav2Lip bash install/install_wav2lip.sh
ENGINE=wav2lip WAV2LIP_DIR=$PWD/engines/Wav2Lip uvicorn app.main:app --port 8000
# http://localhost:8000
```

---

## Guía para obtener el mejor resultado

**Sesión de aprendizaje** (la calidad final depende sobre todo de este paso):

- Rostro de frente, cámara a la altura de los ojos y encuadre tipo presentador.
- Luz frontal difusa, sin contraluz. Use un fondo y ropa iguales a los que quiere en el video final.
- **Labios relajados o casi cerrados**, con parpadeos y movimientos de cabeza suaves y naturales. La boca se regenera, así que el resto de los gestos sale de esta grabación.
- Grabe entre 20 y 40 s. El video final recorre esos cuadros de ida y vuelta mientras dure el audio.

**Audio:**

- Use voz limpia, sin música ni eco.
- El motor responde a la fonética, así que funciona con cualquier idioma.

### Controles automáticos de calidad

Se verifican la duración, un único rostro frontal (≥ 85 % de los cuadros), el tamaño del rostro, la iluminación, la nitidez (varianza del laplaciano), la estabilidad de la cabeza y la resolución mínima de 480 p. Si falla un control crítico, el aprendizaje se bloquea, salvo que usted lo **fuerce**.

---

## Uso responsable

- Use la herramienta **solo con su propia imagen**, o con la autorización expresa y escrita de la persona. La interfaz exige esta declaración.
- Etiquete el contenido sintético. La marca de agua viene activada por defecto.
- Para uso institucional, conserve la autorización y el video fuente de la sesión de aprendizaje.
- Los pesos de Wav2Lip **no permiten uso comercial**. Para eso use MuseTalk (MIT).

## Variables de entorno

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `ENGINE` | `wav2lip` | `musetalk`, `wav2lip` o `mock` |
| `APP_TOKEN` | vacío | Clave de acceso. Si está vacía, el acceso queda abierto. |
| `DATA_DIR` | `./data` | Avatares, audios, videos y trabajos |
| `WAV2LIP_DIR` / `MUSETALK_DIR` | `/opt/...` | Rutas de los motores |
| `W2L_BATCH` / `BATCH_SIZE` | 32 / 20 | Tamaño de lote de inferencia |
| `MAX_ENROLL_SECONDS` / `MAX_AUDIO_SECONDS` | 90 / 900 | Duración máxima del video de aprendizaje y del audio |
| `WATERMARK_TEXT` | Contenido generado con IA | Texto de la marca de agua |

## Estructura

```
app/main.py          API REST y servidor de la interfaz
app/enrollment.py    Análisis de calidad de la sesión de aprendizaje
app/engines.py       Motores MuseTalk, Wav2Lip y de prueba (interfaz común prepare/generate)
app/w2l_runner.py    Ejecutor optimizado de Wav2Lip (detección cacheada, ping-pong, máscara suave)
app/jobs.py          Cola persistente de trabajos
app/media.py         FFmpeg: normalización, marca de agua, miniaturas
static/              Interfaz web (cámara, micrófono, generación)
install/             Instaladores de motores y pesos
kaggle/              Cuaderno para GPU gratuita
```

## Referencias

- Zhang, Y., Zhong, Z., Liu, M., Chen, Z., Wu, B., Zeng, Y., Zhan, C., He, Y., Huang, J. y Zhou, W. (2024). *MuseTalk: Real-Time High-Fidelity Video Dubbing via Spatio-Temporal Sampling*. arXiv:2410.10122. https://doi.org/10.48550/arXiv.2410.10122. Código: https://github.com/TMElyralab/MuseTalk
- Prajwal, K. R., Mukhopadhyay, R., Namboodiri, V. P. y Jawahar, C. V. (2020). A Lip Sync Expert Is All You Need for Speech to Lip Generation In the Wild. *Proceedings of the 28th ACM International Conference on Multimedia*, 484–492. https://doi.org/10.1145/3394171.3413532. Código: https://github.com/Rudrabha/Wav2Lip
- Zhang, S., Zhu, X., Lei, Z., Shi, H., Wang, X. y Li, S. Z. (2017). S³FD: Single Shot Scale-Invariant Face Detector. *IEEE International Conference on Computer Vision (ICCV)*, 192–201.
- Yang, Z., Zeng, A., Yuan, C. y Li, Y. (2023). Effective Whole-Body Pose Estimation with Two-Stages Distillation (DWPose). *ICCV Workshops*.
- Radford, A. et al. (2023). Robust Speech Recognition via Large-Scale Weak Supervision (Whisper). *ICML*, PMLR 202.
- Viola, P. y Jones, M. (2001). Rapid Object Detection using a Boosted Cascade of Simple Features. *CVPR*. (Control de calidad con cascadas Haar de OpenCV.)
- EBU R 128 (2020). *Loudness normalisation and permitted maximum level of audio signals*. European Broadcasting Union.
