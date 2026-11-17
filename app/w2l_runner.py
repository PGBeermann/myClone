"""Ejecutor de Wav2Lip (Prajwal et al., ACM Multimedia 2020) optimizado para CPU.

Se ejecuta como proceso aparte (para aislar la memoria y poder usar otro entorno
Python) con el repositorio oficial de Wav2Lip en sys.path:

  python w2l_runner.py prepare  --w2l DIR --video enroll.mp4 --avatar DIR
  python w2l_runner.py generate --w2l DIR --avatar DIR --audio a.wav --out raw.mp4

Mejoras respecto a inference.py original:
  * La detección facial (S3FD) se hace UNA sola vez en la sesión de aprendizaje y se
    guarda (cuadros + cajas suavizadas); generar videos posteriores es mucho más rápido.
  * Recorrido de cuadros en ida y vuelta (ping-pong) para evitar saltos al repetir.
  * Fusión de la boca con máscara difuminada en vez de pegar un rectángulo.
  * Espectrograma mel reimplementado con la API actual de librosa (≥0.10),
    con los mismos hiperparámetros de hparams.py del repositorio original.
  * Codificación directa a H.264 mediante FFmpeg.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

IMG = 96
MEL_STEP = 16
FPS = 25.0
DET_HEIGHT = 480
PADS = (0, 10, 0, 0)  # arriba, abajo, izquierda, derecha (px)


def device():
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def progress(i, n, label):
    print(f"PROGRESO {label} {i}/{n}", flush=True)


# ------------------------------------------------------------------ audio (hparams de Wav2Lip)
def melspectrogram(wav_path: str) -> np.ndarray:
    import librosa
    from scipy import signal
    sr, n_fft, hop, win = 16000, 800, 200, 800
    wav, _ = librosa.load(wav_path, sr=sr)
    wav = signal.lfilter([1, -0.97], [1], wav)                      # preénfasis
    D = librosa.stft(y=wav, n_fft=n_fft, hop_length=hop, win_length=win)
    mel_basis = librosa.filters.mel(sr=sr, n_fft=n_fft, n_mels=80, fmin=55, fmax=7600)
    S = np.dot(mel_basis, np.abs(D))
    min_level = np.exp(-100 / 20 * np.log(10))
    S = 20 * np.log10(np.maximum(min_level, S)) - 20                # amp→dB − ref_level_db
    S = np.clip(8 * ((S + 100) / 100) - 4, -4, 4)                   # normalización simétrica ±4
    if np.isnan(S).any():
        raise ValueError("El espectrograma contiene NaN; el audio podría estar dañado.")
    return S


def mel_chunks(mel: np.ndarray, fps: float) -> list[np.ndarray]:
    chunks, mult, i = [], 80.0 / fps, 0
    while True:
        start = int(i * mult)
        if start + MEL_STEP > mel.shape[1]:
            chunks.append(mel[:, mel.shape[1] - MEL_STEP:])
            break
        chunks.append(mel[:, start:start + MEL_STEP])
        i += 1
    return chunks


# ------------------------------------------------------------------ sesión de aprendizaje
def prepare(args):
    import face_detection  # del repositorio Wav2Lip
    avatar = Path(args.avatar)
    frames_dir = avatar / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(args.video)
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    if not frames:
        raise SystemExit("El video de aprendizaje no tiene cuadros.")
    h, w = frames[0].shape[:2]
    scale = min(1.0, DET_HEIGHT / h)
    print(f"Cuadros: {len(frames)}  Resolución: {w}x{h}  Dispositivo: {device()}", flush=True)

    det = face_detection.FaceAlignment(face_detection.LandmarksType._2D, flip_input=False, device=device())
    small = [cv2.resize(f, (int(w * scale), int(h * scale))) if scale < 1 else f for f in frames]
    bs, boxes, i = args.det_batch, [], 0
    while i < len(small):
        try:
            preds = det.get_detections_for_batch(np.array(small[i:i + bs]))
        except RuntimeError:
            if bs == 1:
                raise
            bs //= 2
            print(f"Memoria insuficiente; lote de detección reducido a {bs}", flush=True)
            continue
        boxes.extend(preds)
        i += len(preds)
        progress(min(i, len(small)), len(small), "deteccion")
    del det

    # Cuadros sin rostro: se interpola con la caja válida más cercana.
    valid = [k for k, b in enumerate(boxes) if b is not None]
    if len(valid) < 0.8 * len(boxes):
        raise SystemExit(f"Rostro detectado solo en {len(valid)}/{len(boxes)} cuadros. Grabe de nuevo, de frente a la cámara.")
    arr = np.zeros((len(boxes), 4), dtype=np.float32)
    for k in range(len(boxes)):
        src = boxes[k] if boxes[k] is not None else boxes[min(valid, key=lambda v: abs(v - k))]
        x1, y1, x2, y2 = (c / scale for c in src)
        arr[k] = (max(0, y1 - PADS[0]), min(h, y2 + PADS[1]), max(0, x1 - PADS[2]), min(w, x2 + PADS[3]))
    # Suavizado temporal (ventana de 5 cuadros), igual que el original.
    T = 5
    sm = arr.copy()
    for k in range(len(arr)):
        win = arr[len(arr) - T:] if k + T > len(arr) else arr[k:k + T]
        sm[k] = win.mean(axis=0)
    np.save(avatar / "boxes.npy", sm.astype(np.int32))

    for k, f in enumerate(frames):
        cv2.imwrite(str(frames_dir / f"{k:06d}.jpg"), f, [cv2.IMWRITE_JPEG_QUALITY, 95])
    (avatar / "w2l_info.json").write_text(json.dumps({"frames": len(frames), "width": w, "height": h,
                                                      "fps": FPS, "missing_faces": len(boxes) - len(valid)}))
    print(f"Aprendizaje listo: {len(frames)} cuadros, {len(boxes) - len(valid)} sin rostro interpolados.", flush=True)


# ------------------------------------------------------------------ generación
def load_model(path: str, dev: str):
    import torch
    from models import Wav2Lip  # del repositorio Wav2Lip
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    state = {k.replace("module.", ""): v for k, v in ckpt["state_dict"].items()}
    model = Wav2Lip()
    model.load_state_dict(state)
    return model.to(dev).eval()


def blend_mask(hh: int, ww: int) -> np.ndarray:
    """Máscara suave que cubre la mitad inferior del rostro (boca, mentón, mejillas bajas)."""
    m = np.zeros((hh, ww), np.float32)
    top = int(hh * 0.45)
    mx = max(2, int(ww * 0.08))
    m[top:hh - 2, mx:ww - mx] = 1.0
    k = max(3, (int(min(hh, ww) * 0.12) // 2) * 2 + 1)
    return cv2.GaussianBlur(m, (k, k), 0)[..., None]


def generate(args):
    import torch
    torch.set_num_threads(max(1, os.cpu_count() or 1))
    avatar = Path(args.avatar)
    info = json.loads((avatar / "w2l_info.json").read_text())
    boxes = np.load(avatar / "boxes.npy")
    n = info["frames"]
    cycle = list(range(n)) + list(range(n - 2, 0, -1)) if n > 2 else list(range(n))

    chunks = mel_chunks(melspectrogram(args.audio), FPS)
    total = len(chunks)
    dev = device()
    print(f"Cuadros a generar: {total}  Dispositivo: {dev}", flush=True)
    model = load_model(args.checkpoint, dev)

    w, h = info["width"], info["height"]
    ff = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                           "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                           "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", args.out],
                          stdin=subprocess.PIPE)
    cache: dict[int, np.ndarray] = {}

    def frame(idx):
        if idx not in cache:
            if len(cache) > 300:
                cache.clear()
            cache[idx] = cv2.imread(str(avatar / "frames" / f"{idx:06d}.jpg"))
        return cache[idx]

    bs = args.batch
    for b0 in range(0, total, bs):
        idxs = [cycle[i % len(cycle)] for i in range(b0, min(total, b0 + bs))]
        faces, fr, co = [], [], []
        for idx in idxs:
            f = frame(idx)
            y1, y2, x1, x2 = boxes[idx]
            faces.append(cv2.resize(f[y1:y2, x1:x2], (IMG, IMG)))
            fr.append(f.copy())
            co.append((y1, y2, x1, x2))
        faces = np.asarray(faces)
        masked = faces.copy()
        masked[:, IMG // 2:] = 0
        img = np.concatenate((masked, faces), axis=3) / 255.0
        mel = np.asarray(chunks[b0:b0 + len(idxs)])[..., None]
        with torch.no_grad():
            pred = model(torch.FloatTensor(mel.transpose(0, 3, 1, 2)).to(dev),
                         torch.FloatTensor(img.transpose(0, 3, 1, 2)).to(dev))
        pred = (pred.cpu().numpy().transpose(0, 2, 3, 1) * 255.0).clip(0, 255).astype(np.uint8)
        for p, f, (y1, y2, x1, x2) in zip(pred, fr, co):
            hh, ww = y2 - y1, x2 - x1
            p = cv2.resize(p, (ww, hh), interpolation=cv2.INTER_CUBIC).astype(np.float32)
            m = blend_mask(hh, ww)
            roi = f[y1:y2, x1:x2].astype(np.float32)
            f[y1:y2, x1:x2] = (p * m + roi * (1 - m)).astype(np.uint8)
            ff.stdin.write(f.tobytes())
        progress(min(b0 + bs, total), total, "sintesis")
    ff.stdin.close()
    if ff.wait() != 0:
        raise SystemExit("FFmpeg no pudo codificar el video.")
    print("Generación terminada.", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "generate"])
    ap.add_argument("--w2l", required=True, help="Ruta al repositorio Wav2Lip")
    ap.add_argument("--avatar", required=True)
    ap.add_argument("--video")
    ap.add_argument("--audio")
    ap.add_argument("--out")
    ap.add_argument("--checkpoint")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--det-batch", type=int, default=8)
    args = ap.parse_args()
    sys.path.insert(0, args.w2l)
    os.chdir(args.w2l)  # face_detection busca sus pesos con rutas relativas al paquete
    prepare(args) if args.cmd == "prepare" else generate(args)


if __name__ == "__main__":
    main()
